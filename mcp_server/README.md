# MCP server

Exposes three tools backed by the Django API in `../sdd_django_demo/`: list signup
users, list users by country, and change a user's password (admin only).

Auth is Google login at the MCP layer, and only at the front door. A caller signs
in with Google to reach any tool; the first request of that session trades the
Google token for a Django token via `POST /api/auth/google/`, and every later
request reuses that Django token without contacting Google again. Tools call the
Django API with the caller's own token, so Django's own permission checks apply to
the real caller.

A caller Google accepts but this project will not sign in - no account here, or an
embargoed one - reaches no tool at all. If Django later stops accepting the Django
token, the Google token is exchanged once more and the call retried; a second
refusal asks the caller to sign in again.

One consequence worth knowing: because Google is not consulted mid-session,
revoking this app's Google access does not lock a caller out immediately. It takes
effect when their session credential expires, which is bounded by the Google
token's own lifetime (about an hour).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment variables

- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` - required. A Google Cloud OAuth
  client (Web application type), with `<MCP_BASE_URL>/auth/callback` added as an
  authorized redirect URI.
- `MCP_BASE_URL` - this server's own public URL, used for the Google OAuth
  callback. Defaults to `http://localhost:8100`.
- `DJANGO_API_BASE` - base URL of the Django API. Defaults to
  `http://localhost:8000/api`.
- `MCP_CREDENTIAL_CACHE_TTL_SECONDS` - ceiling on how long a credential is reused
  before the caller is verified and exchanged again. Defaults to `86400` (a day).
  It is only a ceiling: a credential also expires with the Google token it came
  from, which is sooner, so raising this does not extend a session past that.

The Django app also needs `GOOGLE_OAUTH_CLIENT_IDS` set to the same client id
(comma-separated if there are several), so `/api/auth/google/` accepts tokens
minted for it.

## Run

```bash
python server.py
```
