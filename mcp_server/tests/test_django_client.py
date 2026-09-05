"""Tests for how django_client reads Django's answers.

These go straight at django_client with a fake transport, because the 401-vs-403
distinction is what the whole recovery path turns on: a 401 means the credential
is stale and worth replacing, a 403 means Django answered correctly and replacing
the credential would only get the same refusal. The session-auth tests replace
django_client wholesale, so nothing there would notice this mapping inverting.
"""

import pytest

import django_client


class FakeResponse:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError('not json')
        return self._payload


class FakeClient:
    """Stands in for the shared httpx2.AsyncClient so _send's own error handling
    really runs."""

    def __init__(self, raises=None, response=None):
        self._raises = raises
        self._response = response

    async def request(self, method, url, **kwargs):
        if self._raises is not None:
            raise self._raises
        return self._response


@pytest.fixture
def transport(monkeypatch):
    """Replace the shared HTTP client, leaving every line of django_client in play."""

    def _transport(raises=None, response=None):
        monkeypatch.setattr(django_client, '_client', FakeClient(raises, response))

    return _transport


@pytest.fixture
def responds(monkeypatch):
    """Make the next Django request return a given response, or raise."""

    def _responds(response=None, raises=None):
        async def _send(method, url, **kwargs):
            if raises is not None:
                raise raises
            return response

        monkeypatch.setattr(django_client, '_send', _send)

    return _responds


# --- 401 is a stale credential -----------------------------------------------


async def test_a_401_listing_users_is_a_credential_problem(responds):
    responds(FakeResponse(401, {'detail': 'Invalid token.'}))

    with pytest.raises(django_client.DjangoAuthError):
        await django_client.list_users('stale-token')


async def test_a_401_changing_a_password_is_a_credential_problem(responds):
    responds(FakeResponse(401, {'detail': 'Invalid token.'}))

    with pytest.raises(django_client.DjangoAuthError):
        await django_client.change_password('stale-token', 'ada', 'new-password-1')


async def test_a_401_exchanging_is_a_credential_problem(responds):
    responds(FakeResponse(401, {'detail': 'Google refused that token.'}))

    with pytest.raises(django_client.DjangoAuthError):
        await django_client.exchange_google_token('google-token-a')


# --- 403 is Django's real answer, not a stale credential ---------------------


async def test_a_403_changing_a_password_is_not_a_credential_problem(responds):
    responds(FakeResponse(403, {'detail': 'Only an admin may do that.'}))

    with pytest.raises(django_client.DjangoAPIError) as refusal:
        await django_client.change_password('good-token', 'ada', 'new-password-1')

    assert not isinstance(refusal.value, django_client.DjangoAuthError)
    assert str(refusal.value) == 'Only an admin may do that.'


async def test_a_403_listing_users_is_not_a_credential_problem(responds):
    responds(FakeResponse(403, {'detail': 'Not permitted.'}))

    with pytest.raises(django_client.DjangoAPIError) as refusal:
        await django_client.list_users('good-token')

    assert not isinstance(refusal.value, django_client.DjangoAuthError)


async def test_a_403_exchanging_means_no_account_here_not_a_stale_credential(responds):
    # /api/auth/google/ answers 403 when Google verified the person but this
    # project has no account it will sign in. Exchanging again cannot help, so it
    # must not be reported as a retryable credential failure at the tool layer.
    responds(FakeResponse(403, {'detail': 'No account here.'}))

    with pytest.raises(django_client.DjangoAuthError):
        await django_client.exchange_google_token('google-token-a')


# --- Other failures ----------------------------------------------------------


async def test_a_500_is_an_ordinary_failure(responds):
    responds(FakeResponse(500, None, text='Server Error'))

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await django_client.list_users('good-token')

    assert not isinstance(failure.value, django_client.DjangoAuthError)


async def test_an_unreachable_django_is_reported_not_raised_raw(transport):
    import httpx2

    transport(raises=httpx2.ConnectError('connection refused'))

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await django_client.list_users('good-token')

    assert 'reach' in str(failure.value).lower()


async def test_an_unreachable_django_during_an_exchange_is_reported(transport):
    import httpx2

    transport(raises=httpx2.ConnectError('connection refused'))

    with pytest.raises(django_client.DjangoAPIError):
        await django_client.exchange_google_token('google-token-a')


async def test_a_timeout_is_reported_not_raised_raw(transport):
    import httpx2

    transport(raises=httpx2.ReadTimeout('too slow'))

    with pytest.raises(django_client.DjangoAPIError):
        await django_client.list_users('good-token')


async def test_a_tool_result_field_allowlist_strips_ids_and_emails(responds):
    responds(
        FakeResponse(
            200,
            [
                {
                    'id': 7,
                    'username': 'ada',
                    'email': 'ada@example.com',
                    'country': 'GB',
                    'date_joined': '2026-01-01',
                }
            ],
        )
    )

    rows = await django_client.list_users('good-token')

    assert rows == [{'username': 'ada', 'country': 'GB', 'date_joined': '2026-01-01'}]


# --- _detail truncates a non-JSON fallback ------------------------------------


async def test_detail_returns_a_short_non_json_body_unchanged(responds):
    responds(FakeResponse(500, None, text='Server Error'))

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await django_client.list_users('good-token')

    assert str(failure.value) == 'Server Error'


async def test_detail_truncates_a_long_non_json_body(responds):
    huge_debug_page = '<html>' + ('x' * 5000) + '</html>'
    responds(FakeResponse(500, None, text=huge_debug_page))

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await django_client.list_users('good-token')

    message = str(failure.value)
    assert len(message) <= django_client.DETAIL_FALLBACK_MAX_LENGTH + len('...')
    assert message.endswith('...')
    assert message != huge_debug_page


async def test_detail_still_returns_a_json_detail_message_in_full(responds):
    # A real 'detail' field, however long, is not the thing being truncated - only
    # the non-JSON fallback is.
    long_detail = 'A' * 500
    responds(FakeResponse(403, {'detail': long_detail}))

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await django_client.list_users('good-token')

    assert str(failure.value) == long_detail


# --- change_password refuses an ambiguous username match -----------------------


async def test_change_password_rejects_no_match(responds):
    responds(FakeResponse(200, []))

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await django_client.change_password('good-token', 'nobody', 'new-password-1')

    assert not isinstance(failure.value, django_client.DjangoAuthError)


async def test_change_password_rejects_an_ambiguous_username_match(responds):
    responds(
        FakeResponse(
            200,
            [
                {'id': 1, 'username': 'ada', 'country': 'GB'},
                {'id': 2, 'username': 'ADA', 'country': 'US'},
            ],
        )
    )

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await django_client.change_password('good-token', 'ada', 'new-password-1')

    assert not isinstance(failure.value, django_client.DjangoAuthError)
    assert 'more than one' in str(failure.value).lower()
