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

django_client = httpx2.AsyncClient(base_url=DJANGO_API_BASE, timeout=REQUEST_TIMEOUT)

# id and email are deliberately left out - internal identifiers and PII the tools don't need.
USER_FIELDS = ('username', 'country', 'date_joined')

# Bounds the fallback used when Django doesn't send a JSON `detail` - an unhandled
# Django error can be a full HTML debug page, which has no business in an LLM's context.
DETAIL_FALLBACK_MAX_LENGTH = 200


class DjangoAPIError(Exception):
    """A Django call did not succeed. Carries the server's own detail message."""


class DjangoAuthError(DjangoAPIError):
    """The credential this call was made with is not one Django will accept.

    Kept apart from its parent because only this case is worth retrying with a
    fresh credential. A 403 from list_users/change_password - a non-admin calling
    an admin-only endpoint, an embargoed account - is Django answering correctly,
    and re-exchanging would turn a clear refusal into a retry that refuses again.
    """


async def send_request(method, path, **kwargs):
    try:
        return await django_client.request(method, path, **kwargs)
    except httpx2.RequestError as err:
        raise DjangoAPIError('Could not reach the API.') from err


async def exchange_google_token(google_access_token):
    """Trade a verified Google access token for this project's own DRF token."""
    response = await send_request(
        'POST', '/auth/google/', json={'access_token': google_access_token}
    )

    # 401 is Google refusing the token, 403 is this project having no account it
    # will sign in. Neither is transient, and both mean the same thing to a
    # caller: there is no credential to be had here.
    if response.status_code in (401, 403):
        raise DjangoAuthError(extract_error_detail(response))
    if response.status_code != 200:
        raise DjangoAPIError(extract_error_detail(response))

    return response.json()['token']


async def _get_users(django_token, country=None, username=None):
    """The raw, unfiltered rows - id included. Internal use only; never returned
    directly from a tool."""
    params = {}
    if country:
        params['country'] = country
    if username:
        params['username'] = username

    response = await send_request(
        'GET', '/users/', params=params, headers={'Authorization': f'Token {django_token}'}
    )
    if response.status_code == 401:
        raise DjangoAuthError(extract_error_detail(response))
    if response.status_code != 200:
        raise DjangoAPIError(extract_error_detail(response))

    return response.json()


async def list_users(django_token, country=None):
    """Signup users, optionally filtered by country. Stripped to USER_FIELDS."""
    rows = await _get_users(django_token, country=country)
    return [{field: row[field] for field in USER_FIELDS} for row in rows]


async def change_password(django_token, username, new_password):
    """Set a user's password by username, so no internal id ever reaches the LLM."""
    response = await send_request(
        'POST',
        f'/users/{username}/change-password/',
        json={'password': new_password},
        headers={'Authorization': f'Token {django_token}'},
    )
    if response.status_code == 401:
        raise DjangoAuthError(extract_error_detail(response))
    if response.status_code != 200:
        raise DjangoAPIError(extract_error_detail(response))

    return {'detail': 'Password changed.'}


def extract_error_detail(response):
    """Django's own `detail` message, or a length-capped fallback."""
    try:
        payload = response.json()
    except ValueError:
        return truncate_text(response.text)

    if isinstance(payload, dict) and 'detail' in payload:
        return payload['detail']
    return truncate_text(response.text)


def truncate_text(text):
    if len(text) > DETAIL_FALLBACK_MAX_LENGTH:
        return text[:DETAIL_FALLBACK_MAX_LENGTH] + '...'
    return text
