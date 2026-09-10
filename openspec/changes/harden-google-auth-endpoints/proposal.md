## Why

`add-mcp-drf-token-session`'s `/code-review` round 2 found six problems in the Google sign-in
and user-management endpoints these MCP tools call through - none touched by that change, all
pre-existing. One is a configuration bug that silently locks out every client id after the first
in a multi-client deployment; the rest are gaps in what the endpoints check, return, or leak, all
in code that currently has zero tests. `openspec/config.yaml` requires a direct test for
security-sensitive behaviour; this closes both the gaps and that testing debt at once.

## What Changes

- Fix `GOOGLE_OAUTH_CLIENT_IDS`: it filters each id on its stripped form but stores the
  unstripped one, so `"id-a, id-b"` becomes `["id-a", " id-b"]` and `id-b` can never equal
  Google's `aud` claim. Store the stripped value.
- Reject a Google sign-in whose token carries no `hd` claim when `GOOGLE_ALLOWED_HD` is
  configured, instead of falling back to comparing the email's own domain. The `hd` claim is
  Google's attestation of Workspace membership; the email domain is not, so accepting it in
  `hd`'s place defeats the restriction it stands in for. **BREAKING** for a deployment that has
  set `GOOGLE_ALLOWED_HD` and has been relying on this fallback to admit consumer Google accounts
  whose address happens to share that domain - none does today, since the only account with a
  matching email domain is on that same Workspace.
- Compare `GOOGLE_ALLOWED_HD` to the token's hosted domain case-insensitively.
- Strip `email` from `GET /api/users/` - PII the MCP layer already excludes from tool output,
  dropped one layer earlier so a caller reaching the endpoint directly cannot see it either.
  `id` stays: `AdminChangePasswordView`'s URL is keyed on it, and `django_client.change_password`
  reads it from this same response to build that URL - removing it would break that flow, and
  `id` is an internal identifier already kept out of every tool result, not independently
  sensitive the way an email address is. Access stays `IsAuthenticated`, unchanged from today.
- Stop echoing a Django error page's full body into a tool-facing error message: `django_client`
  currently falls back to `response.text` for a non-JSON response, which is Django's own debug
  page when `DJANGO_DEBUG` is on. Truncate or replace it with a generic message instead.
- Refuse an ambiguous username match in `change_user_password`, the same way
  `resolve_google_user` already refuses an ambiguous email match, rather than silently acting on
  the first case-insensitive hit.
- Add tests for `POST /api/auth/google/`, `GET /api/users/`, and
  `POST /api/users/<id>/change-password/` - all three currently untested - covering every
  requirement below plus the existing behaviour they already have.

## Capabilities

### New Capabilities

- `user-management`: listing signed-up users and an admin resetting a user's password -
  `GET /api/users/` and `POST /api/users/<id>/change-password/`. Both endpoints exist in code
  today and have never been specced or tested; this capability covers their existing behaviour
  (access requirements, response shape) plus the field-stripping this change adds.

### Modified Capabilities

- `user-signin`: `GoogleAuthView`'s behaviour changes (client id matching, hosted-domain
  enforcement) even though no requirement in `specs/user-signin/spec.md` currently describes
  Google sign-in at all - the capability's delta adds the requirements this behaviour needs to
  satisfy, since password-based signin is the only signin behaviour specified there today.

## Impact

- `sdd_django_demo/sdd_django_demo/settings.py`: `GOOGLE_OAUTH_CLIENT_IDS` construction.
- `sdd_django_demo/api/google_auth.py`: `_hosted_domain` and its caller in `verify_access_token`.
- `sdd_django_demo/api/serializers.py`: `UserAccountSerializer` field list.
- `sdd_django_demo/api/views.py`: none of the three views' permission classes change.
- `mcp_server/django_client.py`: `_detail`'s fallback, and `change_password`'s username match.
- New tests: `sdd_django_demo/api/test_google_auth.py`, `sdd_django_demo/api/test_user_management.py`
  covering `UserListView` and `AdminChangePasswordView`, and additions to
  `mcp_server/tests/test_django_client.py`.
- No new model, migration, endpoint, or dependency.
