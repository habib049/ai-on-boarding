"""Fixtures for the session-auth tests.

Every fixture here is a stand-in for something across the network - Google, or the
Django API. No test in this directory makes a real request, and each fake counts
what it was asked to do, so a test can assert on how many times Google or Django
was called, which is most of what this change is about.
"""

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# server.py reads these at import time to build the GoogleProvider.
os.environ.setdefault('GOOGLE_CLIENT_ID', 'test-client-id.apps.googleusercontent.com')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'test-client-secret')

from fastmcp.server.auth.auth import AccessToken  # noqa: E402

import django_client  # noqa: E402
import server  # noqa: E402


def google_access_token(google_token, subject='google-sub-1'):
    """What a real GoogleTokenVerifier returns for a token Google accepts."""
    return AccessToken(
        token=google_token,
        client_id=subject,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email'],
        expires_at=int(time.time()) + 3600,
        subject=subject,
        claims={'sub': subject, 'email': f'{subject}@example.com'},
    )


class FakeGoogleVerifier:
    """The verifier CredentialVerifier wraps - i.e. Google itself."""

    def __init__(self):
        self.calls = []
        self.refuse = set()
        self.subjects = {}

    async def verify_token(self, token):
        self.calls.append(token)
        if token in self.refuse:
            return None
        return google_access_token(token, self.subjects.get(token, 'google-sub-1'))

    @property
    def call_count(self):
        return len(self.calls)


class FakeDjango:
    """The Django API, as django_client sees it."""

    def __init__(self):
        self.exchanges = []
        self.calls = []
        self.tokens_for = {}
        self.next_tokens = []
        self.exchange_error = None
        self.rejects = set()
        self.error = None

    async def exchange_google_token(self, google_token):
        self.exchanges.append(google_token)
        if self.exchange_error is not None:
            raise self.exchange_error
        if self.next_tokens:
            return self.next_tokens.pop(0)
        return self.tokens_for.get(google_token, f'drf-for-{google_token}')

    async def list_users(self, django_token, country=None):
        self._check(django_token, ('list_users', django_token, country))
        rows = [{'username': 'ada', 'country': 'GB', 'date_joined': '2026-01-01'}]
        return [r for r in rows if country is None or r['country'] == country]

    async def change_password(self, django_token, username, new_password):
        self._check(django_token, ('change_password', django_token, username))
        return {'detail': 'Password changed.'}

    def _check(self, django_token, record):
        self.calls.append(record)
        if django_token in self.rejects:
            raise django_client.DjangoAuthError('Invalid token.')
        if self.error is not None:
            raise self.error

    @property
    def exchange_count(self):
        return len(self.exchanges)


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogleVerifier()
    monkeypatch.setattr(server.auth._token_validator, '_inner', fake)
    return fake


@pytest.fixture
def django(monkeypatch):
    fake = FakeDjango()
    for name in ('exchange_google_token', 'list_users', 'change_password'):
        monkeypatch.setattr(django_client, name, getattr(fake, name))
    return fake


@pytest.fixture
def cache(monkeypatch):
    """A cache empty at the start of every test, shared by the verifier and tools."""
    fresh = server.CredentialCache(ttl_seconds=server.CREDENTIAL_CACHE_TTL_SECONDS)
    monkeypatch.setattr(server, '_credentials', fresh)
    monkeypatch.setattr(server.auth._token_validator, '_cache', fresh)
    return fresh


@pytest.fixture
def sign_in(google, django, cache, monkeypatch):
    """Sign a caller in and make their session the one the tools see.

    Returns the AccessToken FastMCP would hand the tools, or None if the caller was
    refused - which is what makes them unable to reach any tool.
    """

    async def _sign_in(google_token='google-token-1'):
        verified = await server.auth._token_validator.verify_token(google_token)
        if verified is not None:
            monkeypatch.setattr(server, 'get_access_token', lambda: verified)
        return verified

    return _sign_in


@pytest.fixture
def as_caller(monkeypatch):
    """Switch the current caller to an already-verified session."""

    def _as_caller(access_token):
        monkeypatch.setattr(server, 'get_access_token', lambda: access_token)

    return _as_caller


@pytest.fixture
def verified_google_token():
    """The AccessToken a real Google verifier returns, for cache-level tests."""
    return google_access_token
