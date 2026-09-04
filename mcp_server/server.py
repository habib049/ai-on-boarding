"""MCP server exposing signup-reporting tools backed by the Django API.

Auth is Google login at the MCP layer (GoogleProvider): a caller must sign in with
Google before any tool is reachable. Each tool then trades the caller's Google
access token for this project's own Django token (see django_client.exchange_google_token)
and calls the Django API with it, so every existing permission check there - who can
list users, who can change a password - applies to the real caller, not to a
blanket service credential.
"""

import os
import time

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token
from fastmcp.utilities.token_cache import TokenCache

import django_client

load_dotenv()

MCP_BASE_URL = os.environ.get('MCP_BASE_URL', 'http://localhost:8100')

# How long a verified Google token is trusted before FastMCP checks with Google
# again. TokenCache also caps this at the token's own expiry, so this is a
# ceiling, not a guarantee of staying cached this long.
GOOGLE_TOKEN_CACHE_TTL_SECONDS = int(os.environ.get('GOOGLE_TOKEN_CACHE_TTL_SECONDS', '300'))

auth = GoogleProvider(
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    base_url=MCP_BASE_URL,
    required_scopes=['openid', 'email'],
)


class CachingGoogleTokenVerifier:
    """Wraps GoogleProvider's real verifier with a TTL cache, so a token already
    verified recently skips the network call to Google's tokeninfo endpoint.

    GoogleProvider has no built-in caching (unlike FastMCP's own GitHubProvider,
    which ships this exact pattern with FastMCP's own TokenCache). The
    alternative - overriding OAuthProxy.load_access_token - was ruled out: that
    method is 183 lines handling refresh locking, revocation, and JTI mapping,
    with the Google network call as only one small piece inside it. Wrapping
    the verifier this class delegates to skips that call without touching any
    of the logic around it.
    """

    def __init__(self, inner_verifier, ttl_seconds):
        self._inner = inner_verifier
        self._cache = TokenCache(ttl_seconds=ttl_seconds)

    async def verify_token(self, token):
        is_cached, cached_result = self._cache.get(token)
        if is_cached:
            print('[cache] HIT - skipped the call to Google', flush=True)
            return cached_result

        start = time.perf_counter()
        result = await self._inner.verify_token(token)
        elapsed = time.perf_counter() - start
        print(f'[cache] MISS - called Google, took {elapsed:.3f}s', flush=True)

        if result is not None:
            self._cache.set(token, result)
        return result


auth._token_validator = CachingGoogleTokenVerifier(
    auth._token_validator, ttl_seconds=GOOGLE_TOKEN_CACHE_TTL_SECONDS
)

mcp = FastMCP('django-user-reporting', auth=auth)


async def _django_token():
    """The caller's Django token, obtained via the Google token FastMCP verified."""
    start = time.perf_counter()
    access_token = get_access_token()
    token = await django_client.exchange_google_token(access_token.token)
    print(f'[timing] _django_token: {time.perf_counter() - start:.3f}s', flush=True)
    return token


@mcp.tool()
async def list_signup_users():
    """List every signed-up user (username, country, signup date)."""
    call_start = time.perf_counter()
    token = await _django_token()

    step_start = time.perf_counter()
    result = await django_client.list_users(token)
    print(f'[timing] list_users call: {time.perf_counter() - step_start:.3f}s', flush=True)
    print(f'[timing] list_signup_users total: {time.perf_counter() - call_start:.3f}s', flush=True)
    return result


@mcp.tool()
async def list_users_by_country(country: str):
    """List signed-up users from a specific country."""
    call_start = time.perf_counter()
    token = await _django_token()

    step_start = time.perf_counter()
    result = await django_client.list_users(token, country=country)
    print(f'[timing] list_users call: {time.perf_counter() - step_start:.3f}s', flush=True)
    print(f'[timing] list_users_by_country total: {time.perf_counter() - call_start:.3f}s', flush=True)
    return result


@mcp.tool()
async def change_user_password(username: str, new_password: str):
    """Change a user's password. Only works if the caller is an admin."""
    call_start = time.perf_counter()
    token = await _django_token()

    step_start = time.perf_counter()
    result = await django_client.change_password(token, username, new_password)
    print(f'[timing] change_password call: {time.perf_counter() - step_start:.3f}s', flush=True)
    print(f'[timing] change_user_password total: {time.perf_counter() - call_start:.3f}s', flush=True)
    return result


if __name__ == '__main__':
    mcp.run(transport='http', host='0.0.0.0', port=8100)
