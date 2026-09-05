"""Tests for specs/user-management/spec.md, written from the spec.

Each requirement and what a test needs to observe to protect it:

- List signed-up users -> an authenticated caller gets every user's username,
  country, and signup date.
- Filter the user list by country -> only matching users come back, matched
  case-insensitively.
- Require authentication to list users -> an unauthenticated request is rejected.
- Never expose an email address in the user list -> asserted directly, filtered
  and unfiltered, not only inferred from the fields a success test happens to
  check.
- Let an admin reset a user's password -> succeeds, and the new password actually
  works.
- Refuse a non-admin resetting a password -> rejected, for both an authenticated
  non-admin and an unauthenticated caller, and the password is unchanged.
- Reject a password reset for a nonexistent user -> rejected.
- Reject a weak new password -> rejected.
- Never return the new password -> asserted directly on both the success and the
  rejection paths.
"""

import pytest
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from embargo.rules import record_account_country


@pytest.fixture
def client():
    return APIClient()


def create_account(username, email=None, password='lovelace1', country=None, is_staff=False):
    account = User.objects.create_user(
        username=username, email=email or f'{username}@example.com',
        password=password, is_staff=is_staff,
    )
    if country is not None:
        record_account_country(account, country)
    return account


def authed_client(user):
    client = APIClient()
    token, _ = Token.objects.get_or_create(user=user)
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client


def list_users(client, country=None, username=None):
    params = {}
    if country:
        params['country'] = country
    if username:
        params['username'] = username
    return client.get('/api/users/', params, format='json')


def change_password(client, username, password):
    return client.post(f'/api/users/{username}/change-password/', {'password': password}, format='json')


# --- List signed-up users -------------------------------------------------------


@pytest.mark.django_db
def test_an_authenticated_caller_can_list_users():
    account = create_account('ada', country='gb')
    caller = authed_client(create_account('caller'))

    response = list_users(caller)

    assert response.status_code == 200
    row = next(r for r in response.data if r['username'] == 'ada')
    assert row['country'] == 'gb'
    assert 'date_joined' in row


# --- Filter the user list by country --------------------------------------------


@pytest.mark.django_db
def test_filtering_by_country_returns_only_matching_users():
    create_account('ada', country='gb')
    create_account('grace', country='us')
    caller = authed_client(create_account('caller'))

    response = list_users(caller, country='gb')

    usernames = {row['username'] for row in response.data}
    assert 'ada' in usernames
    assert 'grace' not in usernames


@pytest.mark.django_db
def test_country_filter_is_case_insensitive():
    create_account('ada', country='gb')
    caller = authed_client(create_account('caller'))

    response = list_users(caller, country='GB')

    usernames = {row['username'] for row in response.data}
    assert 'ada' in usernames


# --- Filter the user list by username -------------------------------------------


@pytest.mark.django_db
def test_filtering_by_username_returns_only_that_user():
    create_account('ada', country='gb')
    create_account('grace', country='us')
    caller = authed_client(create_account('caller'))

    response = list_users(caller, username='ada')

    usernames = {row['username'] for row in response.data}
    assert usernames == {'ada'}


@pytest.mark.django_db
def test_username_filter_is_case_insensitive():
    create_account('ada', country='gb')
    caller = authed_client(create_account('caller'))

    response = list_users(caller, username='ADA')

    usernames = {row['username'] for row in response.data}
    assert 'ada' in usernames


# --- Require authentication to list users ---------------------------------------


@pytest.mark.django_db
def test_listing_without_authentication_is_rejected():
    response = list_users(APIClient())

    assert response.status_code in (401, 403)


# --- Never expose an email address in the user list ------------------------------


@pytest.mark.django_db
def test_unfiltered_listing_contains_no_email_address():
    create_account('ada', email='ada@example.com', country='gb')
    caller = authed_client(create_account('caller'))

    response = list_users(caller)

    assert all('email' not in row for row in response.data)


@pytest.mark.django_db
def test_filtered_listing_contains_no_email_address():
    create_account('ada', email='ada@example.com', country='gb')
    caller = authed_client(create_account('caller'))

    response = list_users(caller, country='gb')

    assert all('email' not in row for row in response.data)


# --- Let an admin reset a user's password ----------------------------------------


@pytest.mark.django_db
def test_an_admin_resets_a_valid_password():
    account = create_account('ada')
    admin_client = authed_client(create_account('admin', is_staff=True))

    response = change_password(admin_client, account.username, 'new-password-1')

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.check_password('new-password-1')


# --- Refuse a non-admin resetting a password -------------------------------------


@pytest.mark.django_db
def test_a_non_admin_cannot_reset_a_password():
    account = create_account('ada')
    non_admin_client = authed_client(create_account('regular', is_staff=False))

    response = change_password(non_admin_client, account.username, 'new-password-1')

    assert response.status_code == 403
    account.refresh_from_db()
    assert account.check_password('lovelace1')


@pytest.mark.django_db
def test_an_unauthenticated_caller_cannot_reset_a_password():
    account = create_account('ada')

    response = change_password(APIClient(), account.username, 'new-password-1')

    assert response.status_code in (401, 403)
    account.refresh_from_db()
    assert account.check_password('lovelace1')


# --- Reject a password reset for a nonexistent user ------------------------------


@pytest.mark.django_db
def test_resetting_a_nonexistent_users_password_is_rejected():
    admin_client = authed_client(create_account('admin', is_staff=True))

    response = change_password(admin_client, 'nobody', 'new-password-1')

    assert response.status_code == 404


# --- Reject a weak new password --------------------------------------------------


@pytest.mark.django_db
def test_a_weak_new_password_is_rejected():
    account = create_account('ada')
    admin_client = authed_client(create_account('admin', is_staff=True))

    response = change_password(admin_client, account.username, 'weak')

    assert response.status_code == 400
    account.refresh_from_db()
    assert account.check_password('lovelace1')


# --- Never return the new password -----------------------------------------------


@pytest.mark.django_db
def test_a_successful_reset_response_never_contains_the_new_password():
    account = create_account('ada')
    admin_client = authed_client(create_account('admin', is_staff=True))

    response = change_password(admin_client, account.username, 'new-password-1')

    assert 'new-password-1' not in str(response.data)


@pytest.mark.django_db
def test_a_rejected_resets_response_never_contains_the_submitted_password():
    account = create_account('ada')
    non_admin_client = authed_client(create_account('regular', is_staff=False))

    response = change_password(non_admin_client, account.username, 'attempted-password-1')

    assert 'attempted-password-1' not in str(response.data)
