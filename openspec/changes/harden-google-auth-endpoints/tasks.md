## 1. Configuration and verification fixes

- [x] 1.1 In `sdd_django_demo/sdd_django_demo/settings.py`, store `client_id.strip()` in
  `GOOGLE_OAUTH_CLIENT_IDS`, not the unstripped value
- [x] 1.2 In `sdd_django_demo/api/google_auth.py`, remove `_hosted_domain`'s fallback to the
  email's domain; when `GOOGLE_ALLOWED_HD` is set, require the `hd` claim to be present
- [x] 1.3 Compare the `hd` claim to `GOOGLE_ALLOWED_HD` case-insensitively
- [x] 1.4 When no hosted-domain restriction is configured, confirm a token with no `hd` claim
  still passes (no behaviour change for the unconfigured case)

## 2. Response shaping

- [x] 2.1 In `sdd_django_demo/api/serializers.py`, remove `email` from
  `UserAccountSerializer.Meta.fields`, leaving `id`, `username`, `country`, `date_joined` - `id`
  stays because `django_client.change_password` reads it from this response to build
  `AdminChangePasswordView`'s URL; only `email` is the PII this task removes

## 3. MCP-layer fixes

- [x] 3.1 In `mcp_server/django_client.py`, truncate `_detail`'s non-JSON fallback to a bounded
  length (200 characters) instead of returning `response.text` whole
- [x] 3.2 Give `change_password` the same ambiguity guard `resolve_google_user` uses: take up to
  two case-insensitive username matches and raise if the count is not exactly one

## 4. Tests (after implementation, from the spec)

- [x] 4.1 List every requirement in `specs/user-signin/spec.md`'s ADDED section and
  `specs/user-management/spec.md`, and what a test would need to assert, working only from the
  spec
- [x] 4.2 Write `sdd_django_demo/api/test_google_auth.py` from that list, covering every
  `user-signin` Google requirement: matching account, wrong-audience rejection (including a
  second configured client id), unverified email, no match, ambiguous match, embargoed account,
  hosted-domain match/mismatch/absent-claim/case-insensitivity/unconfigured, identical rejection
  response shape, no token in a rejection
- [x] 4.3 Write `sdd_django_demo/api/test_user_management.py` from that list, covering every
  `user-management` requirement: listing, country filter and its case-insensitivity, unauthenticated
  rejection, no id/email in any listing response, admin password reset success, non-admin and
  unauthenticated rejection, unknown user id, weak password, no password in any response
- [x] 4.4 Add tests in `mcp_server/tests/test_django_client.py` for the truncated `_detail`
  fallback and the username ambiguity guard
- [x] 4.5 Run `pytest` in `sdd_django_demo/` and confirm every test passes
- [x] 4.6 Run `pytest` in `mcp_server/` and confirm every test passes
- [x] 4.7 Prove at least one new test can fail: revert the hosted-domain fix, confirm the right
  test goes red, then restore it

## 5. Traceability and review

- [ ] 5.1 Build `traceability.md` mapping every requirement in `specs/user-signin/spec.md`'s
  ADDED section and `specs/user-management/spec.md` to its code and its test
- [ ] 5.2 Run `/code-review` and record the verdict
- [ ] 5.3 Fix every blocking finding, then run `/code-review` once more (verify-only) for a final
  `Ready to merge:` verdict
