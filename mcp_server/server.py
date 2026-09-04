"""MCP server exposing signup-reporting tools backed by the Django API.

Auth is Google login at the MCP layer (GoogleProvider): a caller must sign in with
Google before any tool is reachable. Each tool then trades the caller's Google
access token for this project's own Django token (see django_client.exchange_google_token)
and calls the Django API with it, so every existing permission check there - who can
list users, who can change a password - applies to the real caller, not to a
blanket service credential.
"""

import os

from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token

import django_client

MCP_BASE_URL = os.environ.get('MCP_BASE_URL', 'http://localhost:8100')

auth = GoogleProvider(
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    base_url=MCP_BASE_URL,
    required_scopes=['openid', 'email'],
)

mcp = FastMCP('django-user-reporting', auth=auth)


async def _django_token():
    """The caller's Django token, obtained via the Google token FastMCP verified."""
    access_token = get_access_token()
    return await django_client.exchange_google_token(access_token.token)


@mcp.tool()
async def list_signup_users():
    """List every signed-up user (username, country, signup date)."""
    token = await _django_token()
    return await django_client.list_users(token)


@mcp.tool()
async def list_users_by_country(country: str):
    """List signed-up users from a specific country."""
    token = await _django_token()
    return await django_client.list_users(token, country=country)


@mcp.tool()
async def change_user_password(username: str, new_password: str):
    """Change a user's password. Only works if the caller is an admin."""
    token = await _django_token()
    return await django_client.change_password(token, username, new_password)


if __name__ == '__main__':
    mcp.run(transport='http', host='0.0.0.0', port=8100)
