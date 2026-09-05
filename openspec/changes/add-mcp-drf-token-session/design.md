## Context

See proposal.md - Why. What matters for the approach is how FastMCP's `GoogleProvider` actually
handles a request, which is not what the shape of the code suggests:

- The MCP client never holds a Google token. `GoogleProvider` is an `OAuthProxy`: it runs the
  Google login itself, stores the resulting Google token server-side, and issues the client a
  FastMCP JWT of its own.
- On every request `OAuthProxy.load_access_token()` verifies that JWT, looks the stored Google
  token up by JTI, and hands it to `self._token_validator.verify_token()` - the single line
  (`server/auth/oauth_proxy/proxy.py:2197`) that produces the Google `tokeninfo` call. Refresh
  locking, revocation, and JTI mapping all sit around that line, not inside it.
- `_token_validator` is therefore the seam the proposal was looking for. It is already used as
  one in `mcp_server/server.py`, and FastMCP's own `GitHubProvider` ships the same pattern. No
  mirror of the 183-line `load_access_token()` is needed, and none should be written.
- Whatever `verify_token` returns is what `get_access_token()` gives a tool, and its `.token`
  attribute is the Google access token - which is what `_django_token()` already exchanges.

Django's side needs nothing: `POST /api/auth/google/` already verifies a Google access token
(audience, verified email, permitted domain) and returns a DRF token. It stays as it is.

## Goals / Non-Goals

**Goals:**

- One credential exchange per session, at the seam above, with the DRF token carried to tools on
  the object they already receive.
- Keep every check `GoogleTokenVerifier` performs today; add the exchange rather than replace the
  verification.
- Make the recovery path (spec: *Recover once from a rejected session credential*) update the
  cached credential, not just the one call that failed.

**Non-Goals:**

- No JWT of our own, no MCP-side user or session model, no new persistence. The credential lives
  in memory for the life of the process, exactly as the Google verification cache does today.
- No change to `sdd_django_demo/`.
- Not a distributed design. The cache is per-process; a second MCP worker simply exchanges once
  itself.

## Decisions

**Wrap `_token_validator`; do not reimplement `load_access_token()`.** A verifier is a single
method, `verify_token(token) -> AccessToken | None`, and everything the proposal wanted to keep
intact lives outside it. Mirroring `load_access_token()` was the stated fallback; it is not
needed and would freeze a copy of 183 lines of FastMCP internals into this repo, to rot at the
next upgrade. *Alternative considered:* subclass `GoogleProvider` and override
`load_access_token` - rejected for that reason.

**On a cache miss, delegate to the real Google verifier first, then exchange.** The wrapper calls
the `GoogleTokenVerifier` it replaces, and only on success posts the same token to
`/api/auth/google/`. This costs two Google round trips on the session's first call (FastMCP's
`tokeninfo`, then Django's) and none afterwards. *Alternative considered:* skip the inner
verifier and build the `AccessToken` from Django's reply alone, for one Google call instead of
two. Rejected: `GoogleAuthView` returns only `{"token": ...}`, so there is no subject, no email,
and no granted scopes to build an honest `AccessToken` from - and `RequireAuthMiddleware` checks
those scopes. One extra call, once per session, is not worth inventing identity for.

**Carry the DRF token in `AccessToken.claims`.** Tools reach it through `get_access_token()`,
which they already call. The object a verifier returns reaches the tool unaltered:
`load_access_token()` copies and edits it only when the provider overrides
`_extract_upstream_claims()` (`proxy.py:2287-2303`), and `GoogleProvider` does not, so
`upstream_claims` is `None` and both patch blocks are skipped. That has a consequence for the
cache - the cached instance would otherwise be handed to the tool by reference, shared between
concurrent requests - so the cache returns a deep copy on every hit, as `TokenCache` does. This
is also why the spec forbids credentials in tool results: `claims` is a server-side object, and
nothing may print or return it.

**Our own cache, not `fastmcp.utilities.token_cache.TokenCache`.** The recovery requirement needs
an entry to be replaceable when Django stops accepting the DRF token; `TokenCache` offers `get`
and `set` and no invalidation, so a stale entry would keep 401-ing and re-exchanging on every
call - the per-request exchange this change exists to remove. The replacement is a small
dict keyed by the SHA-256 of the Google token (never the token itself), holding the `AccessToken`
and an expiry, with `get`, `set`, and `replace_django_token`. *Alternative considered:* keep
`TokenCache` and hold the DRF token in a second dict beside it - rejected, two caches with one
lifetime drift apart.

**Bound the entry by the Google token's own expiry.** The configured TTL is a ceiling
(`MCP_SESSION_CACHE_TTL_SECONDS`, default 86400) and the entry also expires when the Google token
does, roughly an hour. When `OAuthProxy` then refreshes upstream, the Google token changes, so
the cache key changes and the next call verifies and exchanges afresh. That is the mechanism by
which a revoked Google account is eventually noticed, and it is why the spec's "no request to
Google" requirement is scoped to a session whose credential is *already established*.

**A refused credential is never left cached.** On the success path the entry is replaced; on
either failure path it is discarded. Leaving it would wedge the session: every later call would
repeat the same two doomed round trips, and because FastMCP never returns a 401 in that state the
client would never re-run the OAuth flow it was just told to. Discarding makes the next request a
cache miss, which re-verifies, fails, and produces the 401 that sends the caller back to Google.

**Transport failures are reported, not raised raw.** `django_client` turns an unreachable or
slow Django into `DjangoAPIError`, the way `sdd_django_demo/api/google_auth.py` already turns an
unreachable Google into `GoogleTokenError`. Without it an httpx exception escapes `_call_django`
uncaught and the caller never gets the "sign in again" the spec requires.

**Recover on 401 only, never on 403.** `django_client` gains an error type for 401 alone.
A 403 is Django answering the question correctly - a non-admin calling `change_user_password`,
an embargoed account - and re-exchanging would turn a clear refusal into a retry loop that still
refuses. The retry lives in `server.py`, which owns the session's credential; `django_client`
stays the layer that only speaks HTTP.

**Do not lock around a concurrent first exchange.** Two tool calls racing on a cold cache both
exchange; Django's `Token.objects.get_or_create` returns the same DRF token to both, and the
second `set` overwrites an identical entry. A lock would buy nothing.

**Test the MCP server in its own suite, in its own environment.** `mcp_server/` has never had a
test; `pytest.ini` lives in `sdd_django_demo/`, and `mcp_server/.venv` has neither pytest nor
`fastmcp` in common with it, so a test importing `server.py` cannot be collected by the existing
run. This change adds `mcp_server/tests/` with its own `pytest.ini`, and adds `pytest` and
`pytest-asyncio` to `mcp_server/requirements.txt` - the first new dependencies here, and only
test-time ones. The spec's requirements are about credential handling, which is exactly the
"security-sensitive behaviour needs a test that asserts it directly" case, so leaving them
unasserted is not an option. Django's suite is unaffected and still runs as it does today.
*Alternative considered:* one merged suite at the repo root - rejected, it would mean a single
environment carrying both Django and FastMCP, which nothing else in this repo needs.

## Risks / Trade-offs

- **A caller whose Google access is revoked keeps working for up to the Google token's remaining
  lifetime.** → Accepted deliberately (proposal, *What Changes*). Bounded by the cache entry
  expiring with the Google token, after which the exchange runs again and Django asks Google.
- **The DRF token now sits in an in-memory structure and in `AccessToken.claims`.** → Cache keys
  are hashes, never tokens; the spec requires a test that no tool result or error carries a
  credential; the existing `django_client` field allowlist already keeps tool output to
  `USER_FIELDS`.
- **Django's `GOOGLE_OAUTH_CLIENT_IDS` must contain the MCP server's `GOOGLE_CLIENT_ID`.** →
  Already true today, since the exchange already happens on every call; this change makes the
  failure show up at session start rather than per call, which is easier to diagnose, not harder.
- **A DRF token revoked *and* re-issued while a session is live costs one extra failed call.** →
  The recovery path repairs the cache on that call, so the cost is paid once, not repeatedly.
- **"`pytest` passes for the whole project" now means two commands, not one.** → The archive
  convention (`openspec/config.yaml`, `operations.archive.guidance`) is satisfied by running both
  suites; tasks.md names both explicitly so neither is forgotten.
- **Removing the 5-minute Google verification cache changes an operator-visible knob.** →
  `GOOGLE_TOKEN_CACHE_TTL_SECONDS` disappears and `MCP_SESSION_CACHE_TTL_SECONDS` replaces it;
  both default sensibly, so no deployment must set either.

## Migration Plan

No data migration and no coordinated deploy: the change is confined to the MCP server process.
Restarting it drops all cached credentials, and the next call re-establishes them. Rolling back
is reverting `mcp_server/` - the Django API is untouched, so a rolled-back MCP server and the
current Django API still work together.
