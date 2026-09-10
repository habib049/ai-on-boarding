## Context

See proposal.md for why. Two things about the existing code shape the approach:

- `resolve_google_user` (in `sdd_django_demo/api/views.py`) already refuses an ambiguous email
  match by taking two rows and checking the count is exactly one. `change_user_password`'s
  username match in `mcp_server/django_client.py` does the same case-insensitive lookup but takes
  `next(...)` on the first hit - the same shape of bug `resolve_google_user` was already written
  to avoid, just not applied consistently.
- `django_client._detail` exists precisely to keep a raw response out of an error message - "the
  server's own detail message" per its docstring - but its `except ValueError` fallback returns
  `response.text` whole, which for a non-JSON body is the exact thing it was written to avoid.

## Goals / Non-Goals

**Goals:**

- Fix each of the six findings with the smallest change that satisfies the spec's requirements.
- Give `GoogleAuthView`, `UserListView`, and `AdminChangePasswordView` their first tests, written
  from `specs/user-signin/spec.md` and `specs/user-management/spec.md`, not from reading the
  code - `openspec/config.yaml`'s tasks rule applies here as much as to any other change.
- Keep `GET /api/users/`'s access as `IsAuthenticated` - confirmed with the user rather than
  assumed, since narrowing it to admin-only would silently break `list_signup_users` and
  `list_users_by_country` for every non-admin MCP caller today.

**Non-Goals:**

- No new endpoint, model, or migration.
- No change to password-based signin, signup, password reset, or the embargo rules - this change
  touches only the code the six findings named.
- No change to the MCP-layer recovery path added by `add-mcp-drf-token-session` - `_detail` and
  `change_password` change what they return and raise, not how `_call_django` reacts to them.

## Decisions

**Store the stripped client id, not just filter on it.** `GOOGLE_OAUTH_CLIENT_IDS`'s list
comprehension becomes `client_id.strip() for client_id in ... if client_id.strip()`. One-line
fix; no alternative considered.

**Reject a missing `hd` claim when a domain restriction is configured, rather than deriving one
from the email.** `_hosted_domain`'s fallback treats the email's domain as equivalent to Google's
own attestation of Workspace membership, but nothing about an access token's `email` claim is
Google vouching for organizational membership - `hd` is. Removing the fallback means: no
restriction configured → any `hd` (including absent) passes as before; restriction configured →
`hd` must be present and must match, case-insensitively. *Alternative considered:* keep the
fallback but document the risk - rejected, because the fallback exists specifically to make
`GOOGLE_ALLOWED_HD` mean something, and a documented hole in a security check is still a hole.

**Strip `email` from the serializer; keep `id`.** `UserAccountSerializer.Meta.fields` loses
`email` only. `id` cannot go: `AdminChangePasswordView`'s URL is keyed on it, and
`django_client.change_password` gets that id from this same `GET /api/users/` response -
removing it breaks `change_user_password` outright, not just tidies output. `id` is also not the
same kind of exposure `email` is: it identifies a row, not a person, is already gated behind
`IsAuthenticated`, and is already excluded from every MCP tool result by `django_client.USER_FIELDS`.
*Alternative considered:* strip both and give `AdminChangePasswordView` a username-keyed URL
instead - rejected as a larger, unrelated endpoint change for a finding that email alone already
addresses; `id`'s exposure to an authenticated caller is not the leak the review was pointing at.

**Truncate `_detail`'s non-JSON fallback instead of replacing it outright.** A short prefix of
`response.text` still helps someone debugging a genuine 500, without handing a multi-kilobyte
Django debug page to an LLM's context. Cap at 200 characters. *Alternative considered:* a fixed
generic message with no server text at all - rejected, it throws away information a maintainer
reading a failed tool call would want, for a size problem a truncation already solves.

**Ambiguity guard for `change_password` matches `resolve_google_user`'s shape exactly.** Take up
to two matching rows; if the count is not exactly one, raise - reusing the phrasing already
established in `views.py` rather than inventing a second convention for the same kind of check.

**New capability `user-management`, not a delta on an existing one.** `UserListView` and
`AdminChangePasswordView` have no existing spec of any kind; there is no existing capability's
delta to add to. `user-signin` already exists and already lacks Google signin's requirements, so
that half of this change is a delta on it - the two are different situations and get different
treatment.

## Risks / Trade-offs

- **Rejecting a missing `hd` when a domain is configured could reject a real user who has never
  hit this path.** → No deployment sets `GOOGLE_ALLOWED_HD` today (its own doc-comment gives an
  example, not a default), so this has no live effect until someone opts in, at which point it is
  the restriction actually working rather than a hole in it.
- **The MCP layer's own `USER_FIELDS` allowlist becomes partially redundant with the serializer
  change.** → Deliberately kept: defense in depth for a caller reaching Django directly, not a
  reason to remove the MCP-side allowlist, which still exists for fields Django could add later
  that `USER_FIELDS` would still need to exclude.
- **A username collision that only the ambiguity guard would have caught was, before this change,
  silently resolved to whichever row `next()` found first.** → No behaviour change for the common
  case (usernames are unique in practice, being derived from unique emails); the guard only
  changes what happens in the collision case, from silent to rejected.

## Migration Plan

No data migration. No deploy coordination beyond restarting the Django process and, for the
`django_client` changes, the MCP server. A deployment with `GOOGLE_OAUTH_CLIENT_IDS` set with
extra whitespace starts working correctly rather than needing any action; nothing needs
reconfiguring.
