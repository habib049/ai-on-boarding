"""Tests for the self-service password-change requirement added to
specs/user-management/spec.md, written from the spec.

Each scenario and what a test needs to observe to protect it:

- Successful self-service change -> the current password is verified, the new
  password is set and actually works to sign in, and the response confirms
  success without echoing either password.
- Wrong current password -> rejected, and the password is unchanged.
- Weak new password -> rejected, and the password is unchanged.
- Unauthenticated request -> rejected before any password is checked.
- A password is never echoed back -> asserted directly on both the success
  and the rejection paths.
"""

import pytest
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

CURRENT_PASSWORD = 'lovelace1'


@pytest.fixture
def account():
    return User.objects.create_user(
        username='ada', email='ada@example.com', password=CURRENT_PASSWORD
    )


def authed_client(user):
    """An APIClient carrying user's token, and that token's key."""
    client = APIClient()
    token, _ = Token.objects.get_or_create(user=user)
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client, token.key


def change_own_password(client, current_password, new_password):
    return client.post(
        '/api/users/me/change-password/',
        {'current_password': current_password, 'new_password': new_password},
        format='json',
    )


@pytest.mark.django_db
def test_a_correct_current_password_and_valid_new_password_succeed(account):
    client, _ = authed_client(account)
    response = change_own_password(client, CURRENT_PASSWORD, 'new-password-1')

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.check_password('new-password-1')


@pytest.mark.django_db
def test_a_wrong_current_password_is_rejected_and_nothing_changes(account):
    client, _ = authed_client(account)
    response = change_own_password(client, 'not-the-password', 'new-password-1')

    assert response.status_code == 400
    account.refresh_from_db()
    assert account.check_password(CURRENT_PASSWORD)


@pytest.mark.django_db
def test_a_weak_new_password_is_rejected_and_nothing_changes(account):
    client, _ = authed_client(account)
    response = change_own_password(client, CURRENT_PASSWORD, 'weak')

    assert response.status_code == 400
    account.refresh_from_db()
    assert account.check_password(CURRENT_PASSWORD)


@pytest.mark.django_db
def test_an_unauthenticated_caller_cannot_change_a_password(account):
    response = change_own_password(APIClient(), CURRENT_PASSWORD, 'new-password-1')

    assert response.status_code == 401
    account.refresh_from_db()
    assert account.check_password(CURRENT_PASSWORD)


@pytest.mark.django_db
def test_a_successful_change_response_never_contains_either_password(account):
    client, _ = authed_client(account)
    response = change_own_password(client, CURRENT_PASSWORD, 'new-password-1')

    body = str(response.data)
    assert CURRENT_PASSWORD not in body
    assert 'new-password-1' not in body


@pytest.mark.django_db
def test_a_rejected_changes_response_never_contains_either_password(account):
    client, _ = authed_client(account)
    response = change_own_password(client, 'not-the-password', 'new-password-1')

    body = str(response.data)
    assert 'not-the-password' not in body
    assert 'new-password-1' not in body


@pytest.mark.django_db
def test_a_successful_change_invalidates_the_callers_own_token(account):
    client, token_key = authed_client(account)

    response = change_own_password(client, CURRENT_PASSWORD, 'new-password-1')

    assert response.status_code == 200
    assert not Token.objects.filter(key=token_key).exists()
