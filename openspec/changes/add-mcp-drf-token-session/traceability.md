# Traceability: add-mcp-drf-token-session

Every requirement in `specs/mcp-session-auth/spec.md`, the code that implements it, and the
test that protects it. Tests live in `mcp_server/tests/test_session_auth.py`.

| Requirement | Code | Test |
|---|---|---|
| Establish a session credential at login | `server.py` `SessionCredentialVerifier.verify_token`; `django_client.exchange_google_token` | `test_first_tool_call_of_a_session_exchanges_the_google_token_once`, `test_the_exchanged_token_is_retained_as_the_session_credential` |
| Refuse a caller this project will not sign in | `SessionCredentialVerifier.verify_token` (returns `None` on `DjangoAPIError`); `django_client.exchange_google_token` raising `DjangoAuthError` on 401/403 | `test_a_caller_with_no_account_here_reaches_no_tool`, `test_an_embargoed_caller_reaches_no_tool`, `test_a_refused_caller_is_not_cached_and_is_asked_again` |
| Refuse a caller Google does not recognise | `SessionCredentialVerifier.verify_token` (returns `None` when the wrapped verifier does) | `test_a_caller_google_refuses_reaches_no_tool` |
| Reuse the session credential for every tool call | `SessionCredentialCache.get`; `server.py` `_call_django` reading `claims[DJANGO_TOKEN_CLAIM]` | `test_a_later_tool_call_reuses_the_credential_without_exchanging_again`, `test_two_different_tools_in_one_session_use_the_same_credential` |
| Keep Google out of the request path after login | `SessionCredentialVerifier.verify_token` returning on a cache hit before touching the wrapped verifier; `SessionCredentialCache.set` bounding an entry by the Google token's own expiry | `test_serving_a_later_request_makes_no_google_call`, `test_a_session_expires_with_the_google_token`, `test_a_token_with_no_expiry_does_not_inherit_the_full_ceiling` |
| Recover once from a rejected session credential | `_call_django`; `SessionCredentialCache.replace_django_token`; `DjangoAuthError` raised only on 401 | `test_a_refused_credential_is_replaced_and_the_call_retried`, `test_recovery_exchanges_at_most_once_for_a_single_call`, `test_the_replacement_credential_is_kept_for_later_calls`, `test_a_403_from_django_triggers_no_re_exchange`, and in `test_django_client.py` the direct 401-vs-403 mapping tests this rests on (`test_a_401_listing_users_is_a_credential_problem`, `test_a_403_changing_a_password_is_not_a_credential_problem`, and the four beside them) |
| Fail a call whose recovery does not succeed | `_call_django` raising `DjangoAPIError(SIGN_IN_AGAIN)`; `SessionCredentialCache.discard` on every failure path; `django_client._send` turning an unreachable Django into a `DjangoAPIError` | `test_a_call_fails_when_the_replacement_is_also_refused`, `test_a_call_fails_when_the_fresh_exchange_itself_fails`, `test_a_credential_that_cannot_be_replaced_is_dropped`, `test_a_credential_refused_twice_is_dropped`, `test_a_dropped_session_is_rebuilt_from_scratch`, `test_a_caller_is_told_to_sign_in_when_django_cannot_be_reached`, `test_no_session_is_established_when_django_cannot_be_reached`, `test_an_unreachable_django_is_reported_not_raised_raw`, `test_an_unreachable_django_during_an_exchange_is_reported`, `test_a_timeout_is_reported_not_raised_raw` |
| Confine a session credential to its own caller | `SessionCredentialCache` keyed by the SHA-256 of each caller's own Google token | `test_each_caller_uses_their_own_credential`, `test_one_callers_credential_is_never_served_to_another` |
| Keep the session credential out of tool results | `SIGN_IN_AGAIN`; `django_client.USER_FIELDS` allowlist; no credential in any return value | `test_a_tool_result_carries_no_credential`, `test_a_failure_carries_no_credential`, `test_the_password_a_caller_supplies_never_appears_in_a_result` |

## Review

`/code-review high` (round 1) raised four findings; all four were fixed and each gained a test:
transport failures escaping `_call_django`, a refused credential left cached, no direct test of
the 401-vs-403 mapping, and an expiry-less token inheriting the full 24-hour ceiling. The tests
added for them are listed in the rows above.

Round 2 (verify-only) found no defects in this change: it re-checked the cache key derivation,
the deep-copy handling, the TTL and expiry bounds, the single-recovery path, and the 401-vs-403
split against FastMCP's `oauth_proxy/proxy.py`, and confirmed the tests match the spec's
requirements one for one. Both suites pass (38 in `mcp_server/`, 131 in `sdd_django_demo/`).

Round 2 also returned six findings in code this change does not touch - all in
`sdd_django_demo/`, or in `django_client.py` lines that predate this change. Under the review
contract in CLAUDE.md a follow-up pass "checks only what the first pass raised, plus anything the
fixes broke - it does not go hunting for new material", so these are recorded here and belong to
a separate change, not to this one. Two are serious enough to raise on their own:
`GOOGLE_OAUTH_CLIENT_IDS` in `settings.py` stores unstripped ids so every entry after the first
in a comma-separated list can never match, and the Google sign-in and user-listing endpoints have
no tests at all.

## Falsifiability

`SessionCredentialVerifier.verify_token` was changed to cache failed exchanges as well as
successful ones. `test_a_refused_caller_is_not_cached_and_is_asked_again` failed, and only that
test; the other 19 stayed green. The change was reverted and all 20 pass again.
