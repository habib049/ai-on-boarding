"""MCP server exposing signup-reporting tools backed by the Django API.

Google authenticates a caller once, at the front door. FastMCP runs that login and
keeps the resulting Google token server-side; the first request of a session trades
it for this project's own Django token (see django_client.exchange_google_token),
and every later request in that session reuses the Django token without contacting
Google again. Tools call the Django API with the caller's own token, so every
permission check there - who can list users, who can change a password - applies to
the real caller, not to a blanket service credential.
"""

import hashlib
import os
import time

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token

import django_client

load_dotenv()

MCP_BASE_URL = os.environ.get('MCP_BASE_URL', 'http://localhost:8100')

# Ceiling on how long a credential is reused. It is only a ceiling: an entry also
# expires when the Google token it was established from does, which is sooner (an
# hour, typically). That shorter bound is what eventually notices a revoked Google
# account, so raising this does not extend a revoked credential's life.
CREDENTIAL_CACHE_TTL_SECONDS = int(os.environ.get('MCP_CREDENTIAL_CACHE_TTL_SECONDS', '86400'))
# A learning/reporting tool, not a multi-tenant service - this bounds memory use,
# not expected traffic.
CREDENTIAL_CACHE_MAX_SIZE = 1_000
# Used when a verified token carries no expiry of its own. Google's tokeninfo always
# reports one, but if it ever stops, an entry must not quietly inherit the 24-hour
# ceiling - the short bound is what notices a revoked Google account.
CREDENTIAL_CACHE_FALLBACK_TTL_SECONDS = 3600
_CLEANUP_INTERVAL_SECONDS = 60

# The only Google claims worth keeping. GoogleTokenVerifier's claims dict also
# carries name, picture, locale, and the full raw userinfo response - none of it
# used anywhere here, all of it dead weight in a cache entry kept for up to a day.
GOOGLE_CLAIMS_TO_KEEP = ('sub', 'email')

# What a caller is told when their credential is refused and cannot be replaced.
# Deliberately says nothing about which credential or why - a tool result is read
# by an LLM, and no part of it may carry or hint at a token.
SIGN_IN_AGAIN = 'Your session is no longer valid. Please sign in again.'

# Where the caller's Django token rides on the AccessToken FastMCP hands to a tool.
DJANGO_TOKEN_CLAIM = 'django_token'

auth = GoogleProvider(
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    base_url=MCP_BASE_URL,
    required_scopes=['openid', 'email'],
)


class CredentialCache:
    """The verified identity and Django token for a caller, keyed by their Google token.

    FastMCP's own TokenCache would do everything here except replace an entry, which
    the recovery path needs: without that, a Django token Django has stopped
    accepting would be re-exchanged on every single call - the per-request exchange
    this whole design exists to remove.

    Keys are SHA-256 digests, never the tokens themselves, so a leaked dump of this
    structure's keys yields nothing usable. Entries are handed out as deep copies,
    since FastMCP passes a verifier's result straight through to the tool without
    copying it - returning the stored instance would share one mutable object
    across concurrent requests.
    """

    def __init__(self, ttl_seconds, max_size=CREDENTIAL_CACHE_MAX_SIZE):
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._entries = {}
        self._last_cleanup = time.monotonic()

    def get(self, google_token):
        """The cached AccessToken for this Google token, or None."""
        key = self._key(google_token)
        entry = self._entries.get(key)
        if entry is None:
            return None
        access_token, expires_at = entry
        if expires_at < time.time():
            del self._entries[key]
            return None
        return access_token.model_copy(deep=True)

    def set(self, google_token, access_token):
        """Cache a verified, exchanged AccessToken. Only ever call this on success."""
        key = self._key(google_token)
        self._maybe_cleanup()
        if key not in self._entries:
            self._enforce_size_limit()
        token_expires_at = (
            float(access_token.expires_at)
            if access_token.expires_at
            else time.time() + CREDENTIAL_CACHE_FALLBACK_TTL_SECONDS
        )
        expires_at = min(time.time() + self._ttl, token_expires_at)
        self._entries[key] = (access_token.model_copy(deep=True), expires_at)

    def discard(self, google_token):
        """Forget a session entirely, so the next request rebuilds it from scratch.

        Used when a credential is refused and cannot be replaced: leaving the refused
        one cached would wedge the session, repeating two doomed round trips per call
        while never returning the 401 that makes a client sign in again.
        """
        self._entries.pop(self._key(google_token), None)

    def replace_django_token(self, google_token, django_token):
        """Point an existing entry at a freshly exchanged Django token.

        A no-op if the entry has since expired or been evicted - the next request
        verifies and exchanges from scratch, which is the correct outcome anyway.
        """
        key = self._key(google_token)
        entry = self._entries.get(key)
        if entry is None:
            return
        access_token, expires_at = entry
        replacement = access_token.model_copy(deep=True)
        replacement.claims[DJANGO_TOKEN_CLAIM] = django_token
        self._entries[key] = (replacement, expires_at)

    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def _cleanup_expired(self):
        now = time.time()
        for key in [k for k, (_, expires_at) in self._entries.items() if expires_at < now]:
            del self._entries[key]

    def _maybe_cleanup(self):
        now = time.monotonic()
        if now - self._last_cleanup > _CLEANUP_INTERVAL_SECONDS:
            self._cleanup_expired()
            self._last_cleanup = now

    def _enforce_size_limit(self):
        if len(self._entries) < self._max_size:
            return
        self._cleanup_expired()
        if len(self._entries) >= self._max_size:
            del self._entries[next(iter(self._entries))]


class CredentialVerifier:
    """Verifies a Google token the way GoogleProvider always did, then exchanges it.

    This wraps the verifier at the one point FastMCP calls out to Google on every
    request - OAuthProxy.load_access_token hands the stored Google token to
    self._token_validator.verify_token. Everything around that call (the FastMCP JWT
    check, the JTI lookup, refresh locking, transparent refresh, revocation) is
    untouched, which is why this wraps the verifier rather than reimplementing the
    183-line method that calls it.

    The wrapped verifier still runs on a cache miss, so every check GoogleProvider
    makes today - audience, scopes, expiry - still applies, and the AccessToken this
    returns carries Google's real subject and the granted scopes that
    RequireAuthMiddleware goes on to check.
    """

    def __init__(self, inner_verifier, cache):
        self._inner = inner_verifier
        self._cache = cache

    async def verify_token(self, token):
        cached = self._cache.get(token)
        if cached is not None:
            return cached

        verified = await self._inner.verify_token(token)
        if verified is None:
            return None

        try:
            django_token = await django_client.exchange_google_token(token)
        except django_client.DjangoAPIError:
            # Google knows this person; this project will not sign them in, or could
            # not be reached. Either way there is no credential, so no tool is
            # reachable. Never cached: a refusal must not become sticky.
            return None

        verified.claims = {
            key: value for key, value in verified.claims.items() if key in GOOGLE_CLAIMS_TO_KEEP
        }
        verified.claims[DJANGO_TOKEN_CLAIM] = django_token
        self._cache.set(token, verified)
        return verified


_credentials = CredentialCache(ttl_seconds=CREDENTIAL_CACHE_TTL_SECONDS)
auth._token_validator = CredentialVerifier(auth._token_validator, _credentials)

mcp = FastMCP('django-user-reporting', auth=auth)


async def _call_django(call, *args, **kwargs):
    """Run a Django call with the caller's session credential, repairing it once.

    `call` takes the Django token as its first argument. If Django refuses that
    token, the stored Google token is exchanged for a new one exactly once, the
    cache is repaired so later calls in this session reuse it, and the call is
    retried. A second refusal is the caller's to fix by signing in again.

    Only a 401 comes back as DjangoAuthError, so a 403 - a non-admin calling
    change_user_password, an embargoed account - passes straight through as the
    answer it is, without triggering an exchange.
    """
    access_token = get_access_token()
    try:
        return await call(access_token.claims[DJANGO_TOKEN_CLAIM], *args, **kwargs)
    except django_client.DjangoAuthError:
        pass

    # The retained credential is no longer accepted. It is either replaced below or
    # dropped; it never stays cached, or the session would wedge - repeating two
    # doomed round trips per call while never returning the 401 that makes a client
    # sign in again.
    try:
        django_token = await django_client.exchange_google_token(access_token.token)
    except django_client.DjangoAPIError:
        _credentials.discard(access_token.token)
        raise django_client.DjangoAPIError(SIGN_IN_AGAIN) from None

    _credentials.replace_django_token(access_token.token, django_token)
    try:
        return await call(django_token, *args, **kwargs)
    except django_client.DjangoAuthError:
        # Only a second *credential* refusal is a session problem. Anything else
        # the retry raises is the real answer and must reach the caller intact.
        _credentials.discard(access_token.token)
        raise django_client.DjangoAPIError(SIGN_IN_AGAIN) from None


@mcp.tool()
async def list_signup_users():
    """List every signed-up user (username, country, signup date)."""
    return await _call_django(django_client.list_users)


@mcp.tool()
async def list_users_by_country(country: str):
    """List signed-up users from a specific country."""
    return await _call_django(django_client.list_users, country=country)


@mcp.tool()
async def change_user_password(username: str, new_password: str):
    """Change a user's password. Only works if the caller is an admin."""
    return await _call_django(django_client.change_password, username, new_password)


if __name__ == '__main__':
    mcp.run(transport='http', host='0.0.0.0', port=8100)