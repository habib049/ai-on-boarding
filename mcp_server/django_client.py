"""The only place this server talks to the Django API.

Field allowlists live here, not in the tools: whatever a tool function returns is
what the LLM sees, so stripping ids, emails, and other fields the tools don't need
happens once, in this one layer, rather than being left to every tool author to
remember.
"""

import os

import httpx2

DJANGO_API_BASE = os.environ.get('DJANGO_API_BASE', 'http://localhost:8000/api')
REQUEST_TIMEOUT = 10

# What a tool result is allowed to carry back to the LLM. id and email are
# deliberately left out - internal identifiers and PII the tools don't need.
USER_FIELDS = ('username', 'country', 'date_joined')


class DjangoAPIError(Exception):
    """A Django call did not succeed. Carries the server's own detail message."""


async def exchange_google_token(google_access_token):
    """Trade a verified Google access token for this project's own DRF token."""
    async with httpx2.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(
            f'{DJANGO_API_BASE}/auth/google/',
            json={'access_token': google_access_token},
        )
    if response.status_code != 200:
        raise DjangoAPIError(_detail(response))
    return response.json()['token']


async def _get_users(django_token, country=None):
    """The raw, unfiltered rows - id included. Internal use only; never returned
    directly from a tool."""
    params = {'country': country} if country else {}
    async with httpx2.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(
            f'{DJANGO_API_BASE}/users/',
            params=params,
            headers={'Authorization': f'Token {django_token}'},
        )
    if response.status_code != 200:
        raise DjangoAPIError(_detail(response))
    return response.json()


async def list_users(django_token, country=None):
    """Signup users, optionally filtered by country. Stripped to USER_FIELDS."""
    rows = await _get_users(django_token, country=country)
    return [{field: row[field] for field in USER_FIELDS} for row in rows]


async def change_password(django_token, username, new_password):
    """Set a user's password by username, so no internal id ever reaches the LLM."""
    rows = await _get_users(django_token)
    match = next(
        (row for row in rows if row['username'].lower() == username.lower()), None
    )
    if match is None:
        raise DjangoAPIError(f'No user found with username {username!r}.')

    async with httpx2.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(
            f"{DJANGO_API_BASE}/users/{match['id']}/change-password/",
            json={'password': new_password},
            headers={'Authorization': f'Token {django_token}'},
        )
    if response.status_code != 200:
        raise DjangoAPIError(_detail(response))
    return {'detail': 'Password changed.'}


def _detail(response):
    try:
        return response.json().get('detail', response.text)
    except ValueError:
        return response.text
