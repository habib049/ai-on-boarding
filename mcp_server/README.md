# MCP server

Exposes three tools backed by the Django API in `../sdd_django_demo/`: list signup
users, list users by country, and change a user's password (admin only).

Auth is Google login at the MCP layer. A caller signs in with Google to reach any
tool; each tool call then exchanges that Google token for a Django token via
`POST /api/auth/google/` and calls the Django API with it, so Django's own
permission checks apply to the real caller.

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

The Django app also needs `GOOGLE_OAUTH_CLIENT_IDS` set to the same client id
(comma-separated if there are several), so `/api/auth/google/` accepts tokens
minted for it.

## Run

```bash
python server.py
```
