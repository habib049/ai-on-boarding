"""Tests for specs/user-signin/spec.md's ADDED requirements (Google signin), written
from the spec.

Each requirement and what a test needs to observe to protect it:

- Sign in with a verified Google access token -> a matching account gets a token,
  repeatably.
- Accept only a token issued for this application -> wrong audience is rejected;
  a second configured client id in a multi-client deployment is accepted (this is
  the whitespace-stripping fix - a comma-separated GOOGLE_OAUTH_CLIENT_IDS entry
  after the first must still match).
- Require a verified email address -> an unverified email is rejected.
- Refuse an ambiguous or absent matching account -> no match, and more than one
  match, are both rejected.
- Refuse an embargoed account -> rejected identically to no match.
- Restrict signin to a configured hosted domain -> match, case-insensitive match,
  mismatch, absent hd claim, and no restriction configured, each behave as
  specified - including that an absent `hd` is rejected rather than falling back
  to the email's own domain.
- Identical rejection response for every Google-side refusal -> the same response
  whichever check failed.
- Never return a token in a rejection -> asserted directly on every rejection path,
  not only through the success path.

`api.google_auth.requests.get` - the call to Google's tokeninfo endpoint - is
monkeypatched everywhere, so no test makes a real network call, but
`verify_access_token`'s own audience/verified/hosted-domain logic still runs for
real against whatever claims the fake response carries. That is deliberate: most
of what this suite protects lives inside that logic, not only in `GoogleAuthView`.
"""

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from embargo.rules import record_account_country


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def default_client_id(settings):
    """Every test signs in with aud='the-configured-client-id' unless it overrides
    this itself, so a test not about the audience check doesn't have to think about
    it."""
    settings.GOOGLE_OAUTH_CLIENT_IDS = ['the-configured-client-id']
    settings.GOOGLE_ALLOWED_HD = ''


def google_claims(email='ada@example.com', **overrides):
    claims = {
        'sub': '12345',
        'aud': 'the-configured-client-id',
        'email': email,
        'email_verified': 'true',
    }
    claims.update(overrides)
    return claims


def sign_in_with_google(client):
    return client.post('/api/auth/google/', {'access_token': 'a-google-token'}, format='json')


class FakeTokeninfoResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def accepting(monkeypatch, claims):
    """Make Google's tokeninfo endpoint return these claims - the real
    verify_access_token logic (audience, verified, hosted-domain checks) still runs
    against them, which is what most of these tests are actually exercising."""
    monkeypatch.setattr(
        'api.google_auth.requests.get',
        lambda *a, **k: FakeTokeninfoResponse(200, claims),
    )


def refusing(monkeypatch):
    """Make Google's tokeninfo endpoint refuse the token outright (a non-200)."""
    monkeypatch.setattr(
        'api.google_auth.requests.get',
        lambda *a, **k: FakeTokeninfoResponse(400, {}),
    )


def create_account(username='ada', email='ada@example.com', password='lovelace1'):
    return User.objects.create_user(username=username, email=email, password=password)


# --- Sign in with a verified Google access token ------------------------------


@pytest.mark.django_db
def test_a_matching_account_signs_in(client, monkeypatch):
    create_account()
    accepting(monkeypatch, google_claims())

    response = sign_in_with_google(client)

    assert response.status_code == 200
    assert response.data['token']


@pytest.mark.django_db
def test_signing_in_a_second_time_succeeds_again(client, monkeypatch):
    create_account()
    accepting(monkeypatch, google_claims())

    first = sign_in_with_google(client)
    second = sign_in_with_google(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.data['token']


# --- Accept only a token issued for this application --------------------------


@pytest.mark.django_db
def test_a_token_for_a_different_application_is_rejected(client, monkeypatch, settings):
    settings.GOOGLE_OAUTH_CLIENT_IDS = ['the-configured-client-id']
    create_account()
    accepting(monkeypatch, google_claims(aud='someone-elses-client-id'))

    response = sign_in_with_google(client)

    assert response.status_code == 401
    assert 'token' not in response.data


@pytest.mark.django_db
def test_a_later_configured_client_id_in_a_multi_client_deployment_is_accepted(
    client, monkeypatch, settings
):
    # This is the whitespace-stripping fix: a real deployment sets
    # GOOGLE_OAUTH_CLIENT_IDS from a comma-separated env var, and every entry after
    # the first used to keep a leading space that could never match an aud claim.
    settings.GOOGLE_OAUTH_CLIENT_IDS = ['first-client-id', 'second-client-id']
    create_account()
    accepting(monkeypatch, google_claims(aud='second-client-id'))

    response = sign_in_with_google(client)

    assert response.status_code == 200
    assert response.data['token']


# --- Require a verified email address ------------------------------------------


@pytest.mark.django_db
def test_an_unverified_email_is_rejected(client, monkeypatch):
    create_account()
    accepting(monkeypatch, google_claims(email_verified='false'))

    response = sign_in_with_google(client)

    assert response.status_code == 401
    assert 'token' not in response.data


# --- Refuse an ambiguous or absent matching account ----------------------------


@pytest.mark.django_db
def test_no_matching_account_is_rejected(client, monkeypatch):
    accepting(monkeypatch, google_claims(email='nobody@example.com'))

    response = sign_in_with_google(client)

    assert response.status_code == 403
    assert 'token' not in response.data


@pytest.mark.django_db
def test_more_than_one_matching_account_is_rejected(client, monkeypatch):
    User.objects.create_user(username='ada1', email='ADA@example.com', password='lovelace1')
    User.objects.create_user(username='ada2', email='ada@example.com', password='lovelace2')
    accepting(monkeypatch, google_claims(email='ada@example.com'))

    response = sign_in_with_google(client)

    assert response.status_code == 403
    assert 'token' not in response.data


# --- Refuse an embargoed account -----------------------------------------------


@pytest.mark.django_db
def test_an_embargoed_account_is_rejected(client, monkeypatch):
    account = create_account()
    record_account_country(account, 'erewhon')
    from embargo.models import BlockedCountry

    BlockedCountry.objects.create(country='erewhon')
    accepting(monkeypatch, google_claims())

    response = sign_in_with_google(client)

    assert response.status_code == 403
    assert 'token' not in response.data


# --- Restrict signin to a configured hosted domain -----------------------------


@pytest.mark.django_db
def test_a_matching_hosted_domain_is_accepted(client, monkeypatch, settings):
    settings.GOOGLE_ALLOWED_HD = 'example.com'
    create_account()
    accepting(monkeypatch, google_claims(hd='example.com'))

    response = sign_in_with_google(client)

    assert response.status_code == 200


@pytest.mark.django_db
def test_a_hosted_domain_differing_only_in_case_is_accepted(client, monkeypatch, settings):
    settings.GOOGLE_ALLOWED_HD = 'Example.com'
    create_account()
    accepting(monkeypatch, google_claims(hd='EXAMPLE.COM'))

    response = sign_in_with_google(client)

    assert response.status_code == 200


@pytest.mark.django_db
def test_a_non_matching_hosted_domain_is_rejected(client, monkeypatch, settings):
    settings.GOOGLE_ALLOWED_HD = 'example.com'
    create_account()
    accepting(monkeypatch, google_claims(hd='other.com'))

    response = sign_in_with_google(client)

    assert response.status_code == 401
    assert 'token' not in response.data


@pytest.mark.django_db
def test_an_absent_hosted_domain_claim_is_rejected_when_a_restriction_is_configured(
    client, monkeypatch, settings
):
    # The fix under test: no hd claim must not fall back to the email's own domain,
    # even though that domain happens to equal the configured restriction.
    settings.GOOGLE_ALLOWED_HD = 'example.com'
    create_account()
    accepting(monkeypatch, google_claims(email='ada@example.com'))  # no 'hd' key

    response = sign_in_with_google(client)

    assert response.status_code == 401
    assert 'token' not in response.data


@pytest.mark.django_db
def test_no_hosted_domain_claim_is_fine_when_no_restriction_is_configured(
    client, monkeypatch, settings
):
    settings.GOOGLE_ALLOWED_HD = ''
    create_account()
    accepting(monkeypatch, google_claims())  # no 'hd' key

    response = sign_in_with_google(client)

    assert response.status_code == 200


# --- Identical rejection response for every Google-side refusal ---------------


@pytest.mark.django_db
def test_every_google_side_refusal_gives_the_same_response(client, monkeypatch, settings):
    create_account()

    refusing(monkeypatch)
    unrecognised = sign_in_with_google(client)

    settings.GOOGLE_OAUTH_CLIENT_IDS = ['the-configured-client-id']
    accepting(monkeypatch, google_claims(aud='someone-elses-client-id'))
    wrong_audience = sign_in_with_google(client)

    accepting(monkeypatch, google_claims(email_verified='false'))
    unverified = sign_in_with_google(client)

    settings.GOOGLE_ALLOWED_HD = 'example.com'
    accepting(monkeypatch, google_claims(hd='other.com'))
    wrong_domain = sign_in_with_google(client)

    bodies = {unrecognised.data['detail'], wrong_audience.data['detail'],
              unverified.data['detail'], wrong_domain.data['detail']}
    statuses = {unrecognised.status_code, wrong_audience.status_code,
                unverified.status_code, wrong_domain.status_code}

    assert len(bodies) == 1
    assert len(statuses) == 1


# --- Never return a token in a rejection ---------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    'arrange',
    [
        lambda monkeypatch, settings: refusing(monkeypatch),
        lambda monkeypatch, settings: accepting(monkeypatch, google_claims(email='nobody@x.com')),
    ],
)
def test_no_rejection_response_carries_a_token(client, monkeypatch, settings, arrange):
    arrange(monkeypatch, settings)

    response = sign_in_with_google(client)

    assert response.status_code >= 400
    assert 'token' not in response.data
