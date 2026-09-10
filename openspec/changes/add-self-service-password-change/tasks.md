## 1. Serializer and view

- [x] 1.1 In `sdd_django_demo/api/serializers.py`, add `SelfChangePasswordSerializer` with
  `current_password` (write-only, no strength validator) and `new_password` (write-only,
  `validate_password_strength`)
- [x] 1.2 In `sdd_django_demo/api/views.py`, add `SelfChangePasswordView`
  (`TokenAuthentication`, `IsAuthenticated`) whose `post` verifies `current_password` against
  `request.user.check_password(...)`, rejecting with 400 and no change on a mismatch
- [x] 1.3 On a verified current password, set the new password on `request.user`, delete every
  existing `Token` for that user, and respond `{'detail': 'Password changed.'}` with status 200
- [x] 1.4 Route it in `sdd_django_demo/api/urls.py` as `POST /api/users/me/change-password/`
  and verify `python manage.py show_urls` (or the schema at `/api/schema/`) lists it

## 2. Tests (after implementation, from the spec)

- [x] 2.1 List every scenario in `specs/user-management/spec.md`'s ADDED section and what a test
  would need to assert, working only from the spec
- [x] 2.2 Write `sdd_django_demo/api/test_self_change_password.py` from that list: successful
  change, wrong current password, weak new password, unauthenticated request, and that no
  response body (success or failure) ever contains either password
- [x] 2.3 Add a test asserting the caller's own token stops working immediately after a
  successful change (requires signing in again)
- [x] 2.4 Run `pytest` in `sdd_django_demo/` and confirm every test passes
- [x] 2.5 Prove at least one new test can fail: temporarily skip the current-password check,
  confirm the wrong-current-password test goes red, then restore it

## 3. Traceability and review

- [x] 3.1 Build `traceability.md` mapping every requirement in `specs/user-management/spec.md`'s
  ADDED section to its code and its test
- [x] 3.2 Ensure a GitHub issue exists for this change (comment on issue #46, which already
  tracks the MCP authentication-tools work this endpoint unblocks, rather than opening a
  duplicate) and post the proposal and the full delta spec to it via `gh issue comment`
- [x] 3.3 Run `/code-review` and record the verdict - clean, no findings
- [x] 3.4 Fix every blocking finding, then run `/code-review` once more (verify-only) for a final
  `Ready to merge:` verdict - none to fix; `Ready to merge: yes`
