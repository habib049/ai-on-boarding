## Context

See proposal.md - Why. `AdminChangePasswordView` (`sdd_django_demo/api/views.py`) already sets a
password by username, gated on `IsAdminUser`, with no current-password check, and already
deletes every outstanding token for that user afterward so a changed password takes effect
everywhere. This change adds a second, narrower endpoint for a non-admin caller acting on their
own account.

## Goals / Non-Goals

**Goals:**
- Let the authenticated caller (`request.user`) change their own password, current-password
  verified first.
- Reuse the existing password-strength validator and the existing token-invalidation behavior
  after a password change.

**Non-Goals:**
- Changing `AdminChangePasswordView` or any other existing endpoint.
- Rate-limiting or lockout on repeated wrong-current-password attempts - out of scope here, same
  as the admin endpoint today.

## Decisions

- **New endpoint, not a shared one with the admin endpoint**: `AdminChangePasswordView` operates
  on a username path parameter and never checks a current password; folding self-service into it
  would make "whose account" and "is a current password required" both conditional on caller
  role, which is harder to reason about (and to test) than two small views. `POST
  /api/users/me/change-password/`, authenticated via the same `TokenAuthentication` +
  `IsAuthenticated` pair `UserListView` already uses, acts only on `request.user` - there is no
  username in the URL, so there is no path to another account to guard against.
- **New serializer** (`SelfChangePasswordSerializer`): `current_password` (write-only, no
  validators - it's checked against the stored hash, not judged for strength) and
  `new_password` (write-only, reuses `validate_password_strength`). Current-password verification
  happens in the view via `request.user.check_password(...)`, mirroring how `SigninView` calls
  `authenticate(...)` rather than putting request-scoped checks inside a serializer.
- **Invalidate existing tokens on success**, same as `AdminChangePasswordView` and password
  reset: `Token.objects.filter(user=user).delete()`. The caller's own current token stops working
  along with any others, consistent with "a changed password ends every existing session."

## Risks / Trade-offs

- [Caller is logged out by their own successful call, since their token is deleted] → This
  matches existing behavior for the admin and reset paths; a caller (or the MCP tool calling on
  their behalf) needs to sign in again afterward to get a fresh token.
- [Wrong-current-password attempts are unlimited] → Same exposure `AdminChangePasswordView`
  already has; not introduced by this change, and out of scope to fix here.
