# Django Google Auth Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second way to sign in to the Django app — verify a Google access token and return the same DRF token the existing password sign-in already issues — so the MCP server can act as the real human rather than as a blanket service account.

**Architecture:** Verification only, no OAuth code exchange on the Django side. The MCP server completes the Google login itself (FastMCP's `GoogleProvider`) and posts the resulting access token to a new endpoint. Django asks Google's tokeninfo endpoint whether that token is genuine, checks it was minted for an audience we accept, checks the address is verified and inside the permitted domain, maps it to exactly one existing Django account, and issues that account's existing DRF token. Nothing downstream changes: every existing view, permission class and `IsAdminUser` check keeps working untouched, and the old `/api/signin/` is not modified.

**Tech Stack:** Django 6.1, djangorestframework 3.18, `requests` (new dependency), pytest + pytest-django.

**Spec:** No separate spec file — the design was settled in conversation and is restated in full below. Decisions traceable to the reviewer's guidance: verification-only (no code exchange), check `aud`/`email_verified`/`hd`, return a DRF token rather than a JWT, skip the `load_access_token` override (that is an MCP-side perf choice, unrelated to this endpoint).

## Global Constraints

- Python 3.12+ (Django 6.1 floor); the project's venv is `sdd_django_demo/.venv`.
- All dependencies pinned to exact versions in `sdd_django_demo/requirements.txt`, each with a comment explaining why it is there and when it was added. Match that file's existing style.
- Repo convention (`sdd_django_demo/CLAUDE.md`): **tests are written after implementation, not TDD.** Implementation tasks come first; tests are their own task at the end.
- Repo convention: security-sensitive behaviour (auth, credential storage, credential exposure) needs a test that asserts it directly, not incidentally through a success path. This whole plan is security-sensitive, so Task 4 is not optional.
- Do not modify `/api/signin/`, `SigninView`, the `Token` model, or any existing permission class. This work is purely additive.
- `TokenAuthentication` is imported from `rest_framework.authentication` in this DRF version, **not** `rest_framework.authtoken.authentication` (the latter does not exist here).
- Comment style in this codebase explains *why*, often at length, and is written in prose. Match it; do not write terse one-word comments.

## Design decisions locked in

These were argued out already. Do not relitigate them mid-implementation.

1. **Verification only.** Django never performs the OAuth code exchange and never needs the client secret. It needs the client ID(s) only, for the audience check.
2. **`GOOGLE_OAUTH_CLIENT_IDS` is a list, even with one entry.** If the MCP server is later registered as its own Google application, accepting it becomes a config change rather than a logic change.
3. **The endpoint returns the existing DRF `Token`.** No JWT, no new token type, no new signing key to manage.
4. **An ambiguous email match is refused.** `User.email` has no uniqueness constraint in this project — accounts created via `createsuperuser`, the admin, or a shell bypass the signup path that lowercases and rejects duplicates, and `PasswordResetRequestView` already contains a comment acknowledging that `iexact` can match more than one account. Password reset can safely pick the lowest pk because completing it still requires access to the mailbox. Sign-in cannot: handing out a token for one of two candidate accounts may hand the caller an account that is not theirs.
5. **No auto-creation of accounts.** A verified Google address with no Django account is refused. Signing in must not be a back door around signup, which enforces the country embargo.
6. **The embargo check applies.** `SigninView` refuses an embargoed account before issuing a token. A Google sign-in path that skipped it would be a way around the embargo, so it runs here too.
7. **Google login grants identity, not authority.** `is_staff` is untouched and still has to be granted inside Django. The returned token carries exactly the permissions the mapped account already has.

---

### Task 1: Settings, dependency, and the Google verification module

The verification rules live in their own module rather than inside a view, so they can be tested without constructing a request, and so there is one place that talks to Google.

**Files:**
- Modify: `sdd_django_demo/requirements.txt`
- Modify: `sdd_django_demo/sdd_django_demo/settings.py` (append at end of file)
- Create: `sdd_django_demo/api/google_auth.py`

**Interfaces:**
- Consumes: `django.conf.settings.GOOGLE_OAUTH_CLIENT_IDS` (list of str), `settings.GOOGLE_ALLOWED_HD` (str, empty means unrestricted).
- Produces: `verify_access_token(access_token: str) -> dict` returning Google's claims (keys used later: `email`), raising `GoogleTokenError` on every refusal. Task 3 imports both names from `api.google_auth`.

- [ ] **Step 1: Install `requests` and pin the installed version**

```bash
cd sdd_django_demo
source .venv/bin/activate
pip install requests
pip show requests | grep ^Version
```

Take the version printed and use it verbatim in the next step. Do not guess a version number.

- [ ] **Step 2: Add the pinned dependency to `requirements.txt`**

Insert alphabetically (after `pytest-django`, before `PyYAML`), and add the explanatory comment to the block at the top of the file, matching how `psycopg` and `gunicorn` document themselves:

```
requests==<version from Step 1>
```

And in the header comment block at the top of the file, append:

```
# requests added 2026-09-04, pinned to the current stable release, for the one outbound call
# Google sign-in makes to Google's tokeninfo endpoint - see api/google_auth.py.
```

- [ ] **Step 3: Add the settings**

Append to the end of `sdd_django_demo/sdd_django_demo/settings.py` (`os` is already imported at line 13):

```python
# Google sign-in
#
# This project verifies Google tokens; it never exchanges an authorization code for
# one, so no client secret is needed here - only the client id(s) a token may name as
# its audience.
#
# A list rather than a single value on purpose. The MCP server may be registered with
# Google as its own application rather than sharing this one, and if it is, accepting
# its tokens has to be a config change - adding an entry - and not an edit to the
# check itself.
GOOGLE_OAUTH_CLIENT_IDS = [
    client_id
    for client_id in os.environ.get('GOOGLE_OAUTH_CLIENT_IDS', '').split(',')
    if client_id.strip()
]

# Restrict Google sign-in to one Google Workspace domain, e.g. 'arbisoft.com'. Empty
# means any Google account with a verified address may sign in, provided it already
# has an account here.
GOOGLE_ALLOWED_HD = os.environ.get('GOOGLE_ALLOWED_HD', '')
```

- [ ] **Step 4: Write the verification module**

Create `sdd_django_demo/api/google_auth.py`:

```python
"""Decide whether a Google access token is one this project will sign someone in with.

Kept out of views.py so the rules - which audience is accepted, whether the address
is verified, which hosted domain is required - can be exercised without building a
request, and so there is exactly one place that talks to Google.

Verification, not exchange: the MCP server completes the OAuth flow itself and sends
the resulting access token here. That means this project never handles the client
secret, and needs the client id only to check who the token was minted for.
"""

import requests
from django.conf import settings

# Google's current tokeninfo address. The older
# https://www.googleapis.com/oauth2/v3/tokeninfo answers the same shape if this one
# ever misbehaves.
TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'
TOKENINFO_TIMEOUT = 5


class GoogleTokenError(Exception):
    """A token this project will not sign anyone in with.

    Carries a reason for the log, never for the response: the endpoint answers every
    cause with one body, so a caller cannot use the refusals to map out which
    addresses have accounts or which domain is permitted.
    """


def verify_access_token(access_token):
    """Return Google's claims for an access token, or raise GoogleTokenError.

    Raises if Google does not recognise the token, if it was minted for an audience
    this project does not accept, if the address behind it is unverified or absent,
    or if the account sits outside the permitted hosted domain.
    """
    try:
        response = requests.get(
            TOKENINFO_URL,
            params={'access_token': access_token},
            timeout=TOKENINFO_TIMEOUT,
        )
    except requests.RequestException as err:
        raise GoogleTokenError('Could not reach Google.') from err

    if response.status_code != 200:
        raise GoogleTokenError('Google did not recognise that token.')

    claims = response.json()

    # The audience is the client id the token was minted for. Without this check any
    # other Google application could hand us one of its own users' tokens and be
    # believed: the token is genuine, it was simply never meant for us.
    if claims.get('aud') not in settings.GOOGLE_OAUTH_CLIENT_IDS:
        raise GoogleTokenError('Token was issued for a different application.')

    # tokeninfo reports this as the string 'true', not a JSON boolean, so a plain
    # truthiness test would also pass for the string 'false'.
    if str(claims.get('email_verified', '')).lower() != 'true':
        raise GoogleTokenError('Google has not verified that address.')

    email = claims.get('email')
    if not email:
        raise GoogleTokenError('Token carries no email address.')

    required_domain = settings.GOOGLE_ALLOWED_HD
    if required_domain and _hosted_domain(claims, email) != required_domain:
        raise GoogleTokenError('Account is outside the permitted domain.')

    return claims


def _hosted_domain(claims, email):
    """The Workspace domain behind a token.

    Prefers Google's own `hd` claim, which states outright that the account belongs
    to a Workspace domain. It is not documented as guaranteed on the access-token
    tokeninfo response, so the address is the fallback - safe to read, because it is
    only reached once email_verified has already been established, and Google does
    not verify an address for a domain the account does not hold.
    """
    hosted_domain = claims.get('hd')
    if hosted_domain:
        return hosted_domain
    _, _, domain = email.partition('@')
    return domain
```

- [ ] **Step 5: Confirm the module imports cleanly**

```bash
cd sdd_django_demo && source .venv/bin/activate
python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdd_django_demo.settings')
django.setup()
from api.google_auth import verify_access_token, GoogleTokenError
print('ok', GoogleTokenError.__name__)
"
```

Expected: `ok GoogleTokenError`

- [ ] **Step 6: Commit**

```bash
git add sdd_django_demo/requirements.txt sdd_django_demo/sdd_django_demo/settings.py sdd_django_demo/api/google_auth.py
git commit -m "Add Google access token verification for sign-in

Verification only - no authorization code exchange, so no client secret is
needed here. The audience is checked against a list so a separately
registered MCP client can be accepted by config alone.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The sign-in endpoint

**Files:**
- Modify: `sdd_django_demo/api/serializers.py` (append after `AdminChangePasswordSerializer`)
- Modify: `sdd_django_demo/api/views.py` (imports, response constants near the other body constants, view at end of file)
- Modify: `sdd_django_demo/api/urls.py`

**Interfaces:**
- Consumes: `verify_access_token`, `GoogleTokenError` from `api.google_auth` (Task 1); the existing `TokenSerializer`, `is_user_embargoed`, and `Token` already imported in `views.py`.
- Produces: `POST /api/auth/google/`, url name `google-auth`. Request body `{"access_token": "<google access token>"}`. Responses: `200 {"token": "<drf token key>"}`, `401` on any token problem, `403` when verified but no single usable account matches.

- [ ] **Step 1: Add the serializer**

Append to `sdd_django_demo/api/serializers.py`:

```python
class GoogleAuthSerializer(serializers.Serializer):
    access_token = serializers.CharField(required=True, allow_blank=False, write_only=True)
```

`write_only` matters: it keeps the caller's Google token out of anything DRF renders back, the same reason every password field in this file carries it.

- [ ] **Step 2: Add the imports to `views.py`**

Add to the existing `from .serializers import (...)` block, keeping it alphabetical:

```python
    GoogleAuthSerializer,
```

And add a new import line after the `from embargo.rules import is_user_embargoed` line:

```python
from .google_auth import GoogleTokenError, verify_access_token
```

- [ ] **Step 3: Add the response constants**

Add near the other body constants in `views.py` (below `SIGNIN_REJECTION_BODY`):

```python
# One body for every way a Google token can be refused - unrecognised, minted for
# another application, unverified address, wrong domain, Google unreachable. Four of
# those five say something about how this project is configured, and the fifth says
# nothing useful, so none of them are distinguished in the response.
GOOGLE_REJECTION_BODY = {'detail': 'Unable to sign in with that Google account.'}

# Separate from the body above because the cause is different in kind: the token was
# good, the account here is the problem. Still one body for all three of its causes -
# no account, two accounts, embargoed - so it cannot be used to discover which
# addresses have accounts here.
GOOGLE_NO_ACCOUNT_BODY = {'detail': 'That Google account cannot sign in here.'}
```

- [ ] **Step 4: Add the account resolution helper**

Add to `views.py`, above the view (near the other module-level helpers such as `complete_reset`):

```python
def resolve_google_user(email):
    """The single Django account a verified Google address signs in as, or None.

    Refuses an ambiguous match on purpose. User.email carries no uniqueness
    constraint: accounts made through createsuperuser, the admin, or a shell never
    pass the signup serializer that lowercases the address and rejects duplicates,
    and PasswordResetRequestView already documents that `iexact` can match more than
    one row. Reset can pick the lowest pk and stay safe, because finishing a reset
    still needs the mailbox. Signing in cannot: choosing one of two candidates would
    hand the caller a token for an account that may not be theirs.

    Two rows are enough to know the match is ambiguous, so the query stops there
    rather than counting every duplicate.
    """
    matches = list(User.objects.filter(email__iexact=email).order_by('pk')[:2])
    if len(matches) != 1:
        return None
    return matches[0]
```

- [ ] **Step 5: Add the view**

Append to `sdd_django_demo/api/views.py`:

```python
class GoogleAuthView(generics.GenericAPIView):
    """Sign in with a Google access token obtained elsewhere.

    A second door onto the same room: what comes out is the identical DRF token
    /api/signin/ issues, so every endpoint downstream is unaffected and unchanged.
    This project verifies the token rather than exchanging a code for it, which is
    why it holds no Google client secret.
    """

    serializer_class = GoogleAuthSerializer

    @extend_schema(
        request=GoogleAuthSerializer,
        responses={
            200: OpenApiResponse(response=TokenSerializer, description='Signed in.'),
            400: OpenApiResponse(description='The access_token field was missing or blank.'),
            401: OpenApiResponse(
                description='Google refused the token, it was minted for another '
                'application, its address is unverified, or it is outside the permitted '
                'domain - identical in status and body for all four.'
            ),
            403: OpenApiResponse(
                description='Verified with Google, but no single account here can sign '
                'in - no match, an ambiguous match, or an embargoed account.'
            ),
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            claims = verify_access_token(serializer.validated_data['access_token'])
        except GoogleTokenError:
            return Response(dict(GOOGLE_REJECTION_BODY), status=401)

        user = resolve_google_user(claims['email'])
        if user is None:
            return Response(dict(GOOGLE_NO_ACCOUNT_BODY), status=403)

        # The same gate SigninView applies. Without it this endpoint would be a way
        # around the country embargo for anyone who happens to hold a Google account.
        if is_user_embargoed(user):
            return Response(dict(GOOGLE_NO_ACCOUNT_BODY), status=403)

        token, _ = Token.objects.get_or_create(user=user)
        return Response({'token': token.key}, status=200)
```

- [ ] **Step 6: Add the route**

In `sdd_django_demo/api/urls.py`, add above the `users/` routes:

```python
    path('auth/google/', views.GoogleAuthView.as_view(), name='google-auth'),
```

- [ ] **Step 7: Verify the route resolves and the existing suite still passes**

```bash
cd sdd_django_demo && source .venv/bin/activate
python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdd_django_demo.settings')
django.setup()
from django.urls import reverse
print(reverse('google-auth'))
"
python -m pytest -q
```

Expected: prints `/api/auth/google/`, then `131 passed`.

- [ ] **Step 8: Commit**

```bash
git add sdd_django_demo/api/serializers.py sdd_django_demo/api/views.py sdd_django_demo/api/urls.py
git commit -m "Add Google sign-in endpoint returning the existing DRF token

Refuses an ambiguous email match rather than picking one: User.email has no
uniqueness constraint here, and choosing between two candidates would hand out
a token for an account that may not be the caller's. Applies the same embargo
gate as password sign-in so this is not a way around it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Tests

Written after implementation, per this project's convention. Every refusal path gets a test that asserts it directly — this is auth, so none of it may be covered only incidentally through the success path.

**Files:**
- Create: `sdd_django_demo/api/test_google_auth.py`

**Interfaces:**
- Consumes: `POST /api/auth/google/` (Task 2). Patches `api.google_auth.requests.get` — the module's single outbound call — so no test ever reaches Google.

- [ ] **Step 1: Write the test module**

Create `sdd_django_demo/api/test_google_auth.py`:

```python
from unittest.mock import patch

import pytest
import requests
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from embargo.models import BlockedCountry
from embargo.rules import record_account_country

CLIENT_ID = 'test-client-id.apps.googleusercontent.com'


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def google_settings(settings):
    settings.GOOGLE_OAUTH_CLIENT_IDS = [CLIENT_ID]
    settings.GOOGLE_ALLOWED_HD = ''
    return settings


class FakeResponse:
    """Stands in for what requests.get returns, with only what the module reads."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def google_claims(**overrides):
    claims = {
        'aud': CLIENT_ID,
        'email': 'ada@example.com',
        'email_verified': 'true',
    }
    claims.update(overrides)
    return claims


def create_account(username='ada', email='ada@example.com', password='lovelace1', country=None):
    account = User.objects.create_user(username=username, email=email, password=password)
    if country is not None:
        record_account_country(account, country)
    return account


def google_signin(client, access_token='google-access-token'):
    return client.post(
        '/api/auth/google/', {'access_token': access_token}, format='json'
    )


def with_claims(claims, status_code=200):
    """Patch the one outbound call the module makes."""
    return patch(
        'api.google_auth.requests.get', return_value=FakeResponse(claims, status_code)
    )


@pytest.mark.django_db
def test_google_signin_requires_access_token(client):
    response = client.post('/api/auth/google/', {}, format='json')

    assert response.status_code == 400
    assert 'access_token' in response.data


@pytest.mark.django_db
def test_google_signin_succeeds_for_matching_account(client):
    user = create_account()

    with with_claims(google_claims()):
        response = google_signin(client)

    assert response.status_code == 200
    assert response.data['token'] == Token.objects.get(user=user).key


@pytest.mark.django_db
def test_google_signin_response_shape_is_token_only(client):
    create_account()

    with with_claims(google_claims()):
        response = google_signin(client)

    assert set(response.data.keys()) == {'token'}


@pytest.mark.django_db
def test_google_signin_matches_email_case_insensitively(client):
    user = create_account(email='ada@example.com')

    with with_claims(google_claims(email='ADA@EXAMPLE.COM')):
        response = google_signin(client)

    assert response.status_code == 200
    assert response.data['token'] == Token.objects.get(user=user).key


@pytest.mark.django_db
def test_google_signin_reuses_the_existing_token(client):
    user = create_account()
    existing = Token.objects.create(user=user)

    with with_claims(google_claims()):
        response = google_signin(client)

    assert response.data['token'] == existing.key


@pytest.mark.django_db
def test_google_signin_rejects_token_google_does_not_recognise(client):
    create_account()

    with with_claims({'error': 'invalid_token'}, status_code=400):
        response = google_signin(client)

    assert response.status_code == 401


@pytest.mark.django_db
def test_google_signin_rejects_token_minted_for_another_application(client):
    create_account()

    with with_claims(google_claims(aud='someone-elses-client-id')):
        response = google_signin(client)

    assert response.status_code == 401


@pytest.mark.django_db
def test_google_signin_rejects_unverified_email(client):
    create_account()

    with with_claims(google_claims(email_verified='false')):
        response = google_signin(client)

    assert response.status_code == 401


@pytest.mark.django_db
def test_google_signin_rejects_claims_without_an_email(client):
    create_account()

    claims = google_claims()
    del claims['email']
    with with_claims(claims):
        response = google_signin(client)

    assert response.status_code == 401


@pytest.mark.django_db
def test_google_signin_rejects_account_outside_permitted_domain(client, google_settings):
    google_settings.GOOGLE_ALLOWED_HD = 'arbisoft.com'
    create_account(email='ada@example.com')

    with with_claims(google_claims(hd='example.com')):
        response = google_signin(client)

    assert response.status_code == 401


@pytest.mark.django_db
def test_google_signin_accepts_account_inside_permitted_domain(client, google_settings):
    google_settings.GOOGLE_ALLOWED_HD = 'arbisoft.com'
    user = create_account(email='ada@arbisoft.com')

    with with_claims(google_claims(email='ada@arbisoft.com', hd='arbisoft.com')):
        response = google_signin(client)

    assert response.status_code == 200
    assert response.data['token'] == Token.objects.get(user=user).key


@pytest.mark.django_db
def test_google_signin_falls_back_to_email_domain_when_hd_absent(client, google_settings):
    google_settings.GOOGLE_ALLOWED_HD = 'arbisoft.com'
    user = create_account(email='ada@arbisoft.com')

    with with_claims(google_claims(email='ada@arbisoft.com')):
        response = google_signin(client)

    assert response.status_code == 200
    assert response.data['token'] == Token.objects.get(user=user).key


@pytest.mark.django_db
def test_google_signin_rejects_unreachable_google(client):
    create_account()

    with patch('api.google_auth.requests.get', side_effect=requests.RequestException):
        response = google_signin(client)

    assert response.status_code == 401


@pytest.mark.django_db
def test_google_signin_refuses_when_no_account_matches(client):
    with with_claims(google_claims(email='nobody@example.com')):
        response = google_signin(client)

    assert response.status_code == 403


@pytest.mark.django_db
def test_google_signin_refuses_an_ambiguous_email_match(client):
    create_account(username='ada', email='ada@example.com')
    create_account(username='ada2', email='ADA@example.com')

    with with_claims(google_claims()):
        response = google_signin(client)

    assert response.status_code == 403
    assert not Token.objects.exists()


@pytest.mark.django_db
def test_google_signin_refuses_an_embargoed_account(client):
    create_account(country='India')

    with with_claims(google_claims()):
        response = google_signin(client)

    assert response.status_code == 403
    assert not Token.objects.exists()


@pytest.mark.django_db
def test_google_signin_embargo_applies_to_a_country_blocked_after_signup(client):
    create_account(country='Freedonia')

    with with_claims(google_claims()):
        allowed = google_signin(client)

    BlockedCountry.objects.create(country='Freedonia')
    with with_claims(google_claims()):
        refused = google_signin(client)

    assert allowed.status_code == 200
    assert refused.status_code == 403


@pytest.mark.django_db
def test_google_signin_does_not_create_an_account(client):
    with with_claims(google_claims(email='nobody@example.com')):
        google_signin(client)

    assert not User.objects.filter(email__iexact='nobody@example.com').exists()


@pytest.mark.django_db
def test_google_signin_never_echoes_the_access_token(client):
    create_account()

    with with_claims(google_claims()):
        response = google_signin(client, access_token='super-secret-google-token')

    assert 'super-secret-google-token' not in response.content.decode()


@pytest.mark.django_db
def test_google_signin_does_not_grant_staff(client):
    create_account()

    with with_claims(google_claims()):
        response = google_signin(client)

    token = Token.objects.get(key=response.data['token'])
    assert not token.user.is_staff


@pytest.mark.django_db
def test_google_signin_refusals_are_indistinguishable(client):
    """The four token-level causes must not be tellable apart from the response."""
    create_account()

    with with_claims(google_claims(aud='someone-elses-client-id')):
        wrong_audience = google_signin(client)
    with with_claims(google_claims(email_verified='false')):
        unverified = google_signin(client)
    with with_claims({'error': 'invalid_token'}, status_code=400):
        unrecognised = google_signin(client)

    assert wrong_audience.status_code == unverified.status_code == unrecognised.status_code
    assert wrong_audience.data == unverified.data == unrecognised.data
```

- [ ] **Step 2: Run the new tests**

```bash
cd sdd_django_demo && source .venv/bin/activate
python -m pytest api/test_google_auth.py -v
```

Expected: 21 passed. If `test_google_signin_falls_back_to_email_domain_when_hd_absent` fails, the fallback in `_hosted_domain` is wrong — fix the module, not the test.

- [ ] **Step 3: Run the whole suite**

```bash
python -m pytest -q
```

Expected: 152 passed (131 existing + 21 new).

- [ ] **Step 4: Commit**

```bash
git add sdd_django_demo/api/test_google_auth.py
git commit -m "Test Google sign-in refusals directly

Every rejection path gets its own assertion rather than being covered
incidentally: wrong audience, unverified address, wrong domain, unreachable
Google, no match, ambiguous match, embargoed account. Also asserts the four
token-level refusals are indistinguishable from each other.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Document how to configure and exercise it

**Files:**
- Modify: `sdd_django_demo/README.md`

**Interfaces:**
- Consumes: everything above. Produces no code.

- [ ] **Step 1: Read the README to match its existing structure**

```bash
cd sdd_django_demo && sed -n '1,80p' README.md
```

- [ ] **Step 2: Add a Google sign-in section**

Following whatever heading style the file already uses, document:

- The two environment variables: `GOOGLE_OAUTH_CLIENT_IDS` (comma-separated, no secret required) and `GOOGLE_ALLOWED_HD` (optional, empty means any domain).
- That this project verifies tokens and never exchanges an authorization code, so no client secret is configured here.
- The request and response shape:

```
POST /api/auth/google/
{"access_token": "<token obtained from Google by the client>"}

200 {"token": "<drf token>"}
401  token refused by Google, wrong audience, unverified address, or wrong domain
403  verified, but no single account here can sign in
```

- That the account must already exist — this endpoint never creates one — and that `is_staff` is still granted inside Django, not by Google.

- [ ] **Step 3: Commit**

```bash
git add sdd_django_demo/README.md
git commit -m "Document Google sign-in configuration and request shape

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Out of scope for this plan

These belong to the MCP server, which is a separate process with its own dependencies and needs its own plan once this endpoint exists:

- The FastMCP server itself, `GoogleProvider` configuration, and the OAuth flow.
- Whether to override `load_access_token`. Deliberately skipped for v1 — it trades ~500ms per tool call for a JWT signing key to manage, and it is a performance choice on the MCP side that has nothing to do with this endpoint.
- The client wrappers and their field allowlists (`username`, `country`, `date_joined` out; ids, emails and tokens stripped), including the open question of whether the change-password tool should take a username instead of a user id so internal ids never reach the LLM.
- Registering the application with Google and obtaining a client id.

## Open questions to settle before or during implementation

1. **Does the access-token tokeninfo response actually carry `hd`?** The plan handles both cases (prefers `hd`, falls back to the verified address's domain), so implementation is not blocked, but confirm against a real token and simplify `_hosted_domain` if `hd` is reliably present.
2. **Is refusing an ambiguous email match the behaviour you want?** The alternative is matching the existing `PasswordResetRequestView` behaviour and taking the lowest pk. This plan refuses, on the grounds that sign-in has no second factor the way reset does.
3. **Should this endpoint be throttled?** `PasswordResetRequestView` throttles per address. This one calls out to Google on every request, so an unthrottled endpoint is a way to make this server generate traffic to Google. Not included in v1; worth adding if the endpoint is publicly reachable.
