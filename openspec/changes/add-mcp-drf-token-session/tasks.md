## 1. Django client: a distinguishable rejection

- [x] 1.1 In `mcp_server/django_client.py`, add `DjangoAuthError(DjangoAPIError)` - raised only
  when Django answers 401, so a 403 (non-admin, embargoed) stays an ordinary `DjangoAPIError`
- [x] 1.2 Raise `DjangoAuthError` on a 401 from `_get_users` and from `change_password`'s
  change-password call; leave every other status on the existing `DjangoAPIError` path
- [x] 1.3 Give `exchange_google_token` the same treatment: a 401 or 403 from
  `POST /api/auth/google/` means this caller cannot be signed in, not a transient failure
- [x] 1.4 Remove the `[timing]` `print` calls and the now-unused `time` import left over from the
  diagnostic work in `24635f0`/`7a3abb3`

## 2. Session credential cache

- [x] 2.1 Add `SessionCredentialCache` to `mcp_server/server.py`: entries keyed by the SHA-256
  hex digest of the Google access token (never the token itself), each holding an `AccessToken`
  and an absolute expiry
- [x] 2.2 Implement `get(google_token)`, `set(google_token, access_token)` - expiry being
  `min(now + ttl, access_token.expires_at)` so an entry never outlives the Google token - and
  `replace_django_token(google_token, django_token)` for the recovery path
- [x] 2.3 Bound the cache: sweep expired entries and evict the oldest when full, as
  `fastmcp.utilities.token_cache.TokenCache` does
- [x] 2.4 Read the ceiling from `MCP_SESSION_CACHE_TTL_SECONDS`, default 86400

## 3. Verifier: verify once, exchange once

- [x] 3.1 Replace `CachingGoogleTokenVerifier` with `SessionCredentialVerifier`, wrapping the
  same `auth._token_validator` seam
- [x] 3.2 On a cache hit, return the cached `AccessToken` with no network call at all
- [x] 3.3 On a miss, call the wrapped Google verifier first; return `None` unchanged if it
  refuses, so every check it makes today still applies
- [x] 3.4 On success, exchange the same token via `django_client.exchange_google_token`; return
  `None` if the exchange is refused, so a caller this project will not sign in reaches no tool
- [x] 3.5 Attach the DRF token to the verified `AccessToken`'s `claims` and cache the result
- [x] 3.6 Do not cache failures - neither a Google refusal nor a refused exchange
- [x] 3.7 Delete `GOOGLE_TOKEN_CACHE_TTL_SECONDS` and the `TokenCache` import

## 4. Tools: use the session credential

- [x] 4.1 Rewrite `_django_token()` to read the DRF token from `get_access_token().claims`
  instead of calling `exchange_google_token`
- [x] 4.2 Add a helper in `server.py` that runs a Django call, and on `DjangoAuthError` exchanges
  the Google token from `get_access_token().token` once, updates the cache via
  `replace_django_token`, and retries the call exactly once
- [x] 4.3 Surface a second failure as a message telling the caller to sign in again, carrying no
  credential
- [x] 4.4 Route `list_signup_users`, `list_users_by_country`, and `change_user_password` through
  that helper
- [x] 4.5 Update `server.py`'s module docstring - it currently describes the per-call exchange
  this change removes

## 5. Test environment

- [x] 5.1 Add `pytest` and `pytest-asyncio` to `mcp_server/requirements.txt`, pinned in the
  style of the existing entries, and install them into `mcp_server/.venv`
- [x] 5.2 Add `mcp_server/pytest.ini` (`asyncio_mode = auto`, `python_files = test_*.py`) and an
  empty `mcp_server/tests/` package
- [x] 5.3 Add fixtures faking the wrapped Google verifier and the Django API, so no test reaches
  the network, and so each test can count the calls made to each

## 6. Tests (after implementation, from the spec)

- [x] 6.1 List every requirement in `specs/mcp-session-auth/spec.md` and what a test would need
  to assert, working only from the spec
- [x] 6.2 Write `mcp_server/tests/test_session_auth.py` from that list, covering every
  requirement: one exchange at login; the credential retained and reused across two tools; no
  Google call once established; refusal when Google refuses; refusal when the exchange is
  refused, for both the no-account and embargoed cases; recovery on 401 with exactly one
  re-exchange; failure when recovery also fails; two callers never sharing a credential
- [x] 6.3 Assert the credential requirements directly, not through a success path: no tool
  result and no error message contains a DRF or Google token, and a 403 from Django triggers no
  re-exchange
- [x] 6.4 Run `pytest` in `mcp_server/` and confirm every test passes
- [x] 6.5 Run `pytest` in `sdd_django_demo/` and confirm the Django suite is still green
- [x] 6.6 Prove at least one new test can fail: make the verifier cache failures as well as
  successes, confirm the refusal test goes red, then restore it

## 7. Traceability and review

- [x] 7.1 Build `traceability.md` mapping every requirement in `specs/mcp-session-auth/spec.md`
  to its code and its test
- [x] 7.2 Update `mcp_server/README.md` to describe the session credential and the two
  environment variables (`MCP_SESSION_CACHE_TTL_SECONDS` in, `GOOGLE_TOKEN_CACHE_TTL_SECONDS`
  out)
- [x] 7.3 Run `/code-review` and record the verdict
- [ ] 7.4 Fix every blocking finding, then run `/code-review` once more (verify-only) for a final
  `Ready to merge:` verdict
