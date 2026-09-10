## Why

The only password-change endpoint today is admin-only: it sets any user's password by username
and never checks the caller's current password. A signed-in user has no way to change their own
password without an administrator's help. This blocks the MCP server (issue #46) from exposing a
self-service "change my password" tool, which is part of that issue's required scope.

## What Changes

- Add an endpoint that lets the currently authenticated user change their own password.
- The caller must supply their current password; it is verified before the new password takes
  effect. A wrong current password is rejected and nothing changes.
- The new password is validated with the same strength rule used at signup and password reset.
- Neither the current nor the new password is ever echoed back in a response.
- An unauthenticated call is rejected before any password is checked.

## Capabilities

### Modified Capabilities

- `user-management`: adds a self-service password-change requirement alongside the existing
  admin-initiated one.

## Impact

- New endpoint and view in `sdd_django_demo/api/` (routed in `sdd_django_demo/api/urls.py`).
- New serializer validating current password, new password, and new-password strength.
- No changes to the admin change-password endpoint, signup, signin, or password-reset behavior.
- Enables a corresponding MCP tool in `mcp_server/` (tracked separately, on the MCP branch).
