## Why

Every MCP tool call currently pays for Google twice. FastMCP verifies the caller's stored Google
access token against Google's tokeninfo endpoint on each request, and the Django API this server
calls then verifies that same Google token a second time before handing back a token of its own.
Two round trips to Google stand between a caller asking a question and getting an answer, and
neither of them establishes anything that was not already established when the caller logged in.

Google's role should end at the front door. Once a caller has proved who they are, this project
already has a credential that says so - the token the Django API issues - and it should be the
only one the MCP layer needs from that point on.

## What Changes

- Trade the caller's Google access token for this project's own API token once, when the MCP
  session is first established, instead of on every tool call.
- Reuse that API token as the caller's credential for the rest of the session, so no tool call
  makes a network request to Google.
- **BREAKING** (operationally, not in any request/response contract): after the initial login,
  a caller whose Google access is revoked keeps working until their MCP session expires. Google
  is no longer consulted mid-session, so revocation there is no longer noticed there.
- Recover from a rejected API token by exchanging the stored Google credential a second time and
  retrying once; a caller whose second exchange also fails must log in again.
- Reject a caller whose initial exchange fails, so a person Google recognises but this project
  will not sign in - no matching account, or an embargoed one - cannot reach any tool.
- Remove the per-request Google verification cache introduced to make the old path bearable; it
  has nothing left to cache.

## Capabilities

### New Capabilities

- `mcp-session-auth`: how the MCP server establishes and reuses a caller's credential - the
  single exchange at login, reuse of the resulting API token for every tool call, the absence of
  Google from the request path afterwards, and recovery when that token stops being accepted.

### Modified Capabilities

(none) - the Django API's behaviour is unchanged. `POST /api/auth/google/` still verifies a
Google access token and returns an API token exactly as it does today; this change alters only
how often the MCP server calls it and what it does with the result.

## Impact

- `mcp_server/server.py`: the Google token verifier wrapper is replaced by one that exchanges
  and caches the API token. `CachingGoogleTokenVerifier` and `GOOGLE_TOKEN_CACHE_TTL_SECONDS`
  go away.
- `mcp_server/django_client.py`: tool functions stop calling `exchange_google_token` per call;
  the exchange moves behind the verifier and gains a defined failure path.
- No change to `sdd_django_demo/` - no new endpoint, model, migration, or dependency.
- No change to any HTTP contract a client of the Django API can observe.
