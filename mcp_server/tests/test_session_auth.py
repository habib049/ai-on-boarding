"""Tests for specs/mcp-session-auth/spec.md, written from the spec.

Each requirement and what a test has to observe to protect it:

- Establish a session credential at login -> count the exchanges made across a
  session's first call, and check the credential is kept rather than re-derived.
- Refuse a caller this project will not sign in -> a caller the project declines
  gets no usable session at all, for both the no-account and the embargoed case.
- Refuse a caller Google does not recognise -> same, when the refusal is Google's.
- Reuse the session credential for every tool call -> later calls, and calls to a
  different tool, add no exchanges and carry the same token to Django.
- Keep Google out of the request path after login -> serving a later request adds
  no calls to the Google verifier.
- Recover once from a rejected session credential -> a refused token is replaced
  and the call retried; the replacement is exchanged exactly once.
- Fail a call whose recovery does not succeed -> the caller is told to sign in.
- Confine a session credential to its own caller -> two sessions never cross.
- Keep the session credential out of tool results -> no credential appears in a
  result or in a failure, asserted directly rather than through a success path.
"""

import time

import pytest

import django_client
import server

GOOGLE_A = 'google-token-a'
GOOGLE_B = 'google-token-b'


def django_tokens_used(django):
    return [record[1] for record in django.calls]


# --- Establish a session credential at login ---------------------------------


async def test_first_tool_call_of_a_session_exchanges_the_google_token_once(
    sign_in, django
):
    await sign_in(GOOGLE_A)
    await server.list_signup_users()

    assert django.exchange_count == 1
    assert django.exchanges == [GOOGLE_A]


async def test_the_exchanged_token_is_retained_as_the_session_credential(sign_in, cache):
    verified = await sign_in(GOOGLE_A)

    assert verified.claims[server.DJANGO_TOKEN_CLAIM] == f'drf-for-{GOOGLE_A}'
    assert cache.get(GOOGLE_A) is not None


# --- Refuse a caller this project will not sign in ---------------------------


async def test_a_caller_with_no_account_here_reaches_no_tool(sign_in, django):
    django.exchange_error = django_client.DjangoAuthError('No account.')

    assert await sign_in(GOOGLE_A) is None


async def test_an_embargoed_caller_reaches_no_tool(sign_in, django):
    django.exchange_error = django_client.DjangoAuthError('Account is embargoed.')

    assert await sign_in(GOOGLE_A) is None


async def test_a_refused_caller_is_not_cached_and_is_asked_again(sign_in, django, cache):
    django.exchange_error = django_client.DjangoAuthError('No account.')
    await sign_in(GOOGLE_A)

    assert cache.get(GOOGLE_A) is None

    django.exchange_error = None
    assert await sign_in(GOOGLE_A) is not None


# --- Refuse a caller Google does not recognise -------------------------------


async def test_a_caller_google_refuses_reaches_no_tool(sign_in, google, django):
    google.refuse.add(GOOGLE_A)

    assert await sign_in(GOOGLE_A) is None
    assert django.exchange_count == 0


# --- Reuse the session credential for every tool call ------------------------


async def test_a_later_tool_call_reuses_the_credential_without_exchanging_again(
    sign_in, django
):
    await sign_in(GOOGLE_A)
    await server.list_signup_users()
    await server.list_signup_users()

    assert django.exchange_count == 1
    assert django_tokens_used(django) == [f'drf-for-{GOOGLE_A}'] * 2


async def test_two_different_tools_in_one_session_use_the_same_credential(
    sign_in, django
):
    await sign_in(GOOGLE_A)
    await server.list_signup_users()
    await server.change_user_password('ada', 'new-password-1')

    assert django.exchange_count == 1
    assert set(django_tokens_used(django)) == {f'drf-for-{GOOGLE_A}'}


# --- Keep Google out of the request path after login -------------------------


async def test_serving_a_later_request_makes_no_google_call(sign_in, google, django):
    await sign_in(GOOGLE_A)
    calls_after_login = google.call_count

    # What FastMCP does on every subsequent request, then the tool it guards.
    await server.auth._token_validator.verify_token(GOOGLE_A)
    await server.list_signup_users()

    assert google.call_count == calls_after_login
    assert django.exchange_count == 1


# --- Recover once from a rejected session credential -------------------------


async def test_a_refused_credential_is_replaced_and_the_call_retried(sign_in, django):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.next_tokens = ['drf-replacement']

    result = await server.list_signup_users()

    assert result == [{'username': 'ada', 'country': 'GB', 'date_joined': '2026-01-01'}]
    assert django_tokens_used(django) == [f'drf-for-{GOOGLE_A}', 'drf-replacement']


async def test_recovery_exchanges_at_most_once_for_a_single_call(sign_in, django):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.next_tokens = ['drf-replacement']

    await server.list_signup_users()

    assert django.exchange_count == 2  # one at login, one for the recovery


async def test_the_replacement_credential_is_kept_for_later_calls(sign_in, django):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.next_tokens = ['drf-replacement']
    await server.list_signup_users()

    # A later request re-reads the session from the cache, as FastMCP would.
    verified = await server.auth._token_validator.verify_token(GOOGLE_A)

    assert verified.claims[server.DJANGO_TOKEN_CLAIM] == 'drf-replacement'


async def test_a_403_from_django_triggers_no_re_exchange(sign_in, django):
    await sign_in(GOOGLE_A)
    django.error = django_client.DjangoAPIError('Only an admin may do that.')

    with pytest.raises(django_client.DjangoAPIError) as refusal:
        await server.change_user_password('ada', 'new-password-1')

    assert django.exchange_count == 1
    assert str(refusal.value) == 'Only an admin may do that.'


# --- Fail a call whose recovery does not succeed -----------------------------


async def test_a_call_fails_when_the_replacement_is_also_refused(sign_in, django):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.next_tokens = ['drf-replacement']
    django.rejects.add('drf-replacement')

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await server.list_signup_users()

    assert 'sign in again' in str(failure.value).lower()


async def test_a_call_fails_when_the_fresh_exchange_itself_fails(sign_in, django):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.exchange_error = django_client.DjangoAuthError('No account.')

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await server.list_signup_users()

    assert 'sign in again' in str(failure.value).lower()


# --- Confine a session credential to its own caller --------------------------


async def test_each_caller_uses_their_own_credential(sign_in, as_caller, google, django):
    google.subjects = {GOOGLE_A: 'sub-a', GOOGLE_B: 'sub-b'}
    caller_a = await sign_in(GOOGLE_A)
    caller_b = await sign_in(GOOGLE_B)

    as_caller(caller_a)
    await server.list_signup_users()
    as_caller(caller_b)
    await server.list_signup_users()

    assert django_tokens_used(django) == [f'drf-for-{GOOGLE_A}', f'drf-for-{GOOGLE_B}']


async def test_one_callers_credential_is_never_served_to_another(sign_in, google):
    google.subjects = {GOOGLE_A: 'sub-a', GOOGLE_B: 'sub-b'}
    caller_a = await sign_in(GOOGLE_A)
    caller_b = await sign_in(GOOGLE_B)

    assert (
        caller_a.claims[server.DJANGO_TOKEN_CLAIM]
        != caller_b.claims[server.DJANGO_TOKEN_CLAIM]
    )
    assert caller_a.subject != caller_b.subject


# --- Keep the session credential out of tool results -------------------------


async def test_a_tool_result_carries_no_credential(sign_in):
    await sign_in(GOOGLE_A)

    result = await server.list_signup_users()

    rendered = repr(result)
    assert GOOGLE_A not in rendered
    assert f'drf-for-{GOOGLE_A}' not in rendered


async def test_a_failure_carries_no_credential(sign_in, django):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.next_tokens = ['drf-replacement']
    django.rejects.add('drf-replacement')

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await server.list_signup_users()

    message = str(failure.value)
    assert GOOGLE_A not in message
    assert f'drf-for-{GOOGLE_A}' not in message
    assert 'drf-replacement' not in message


async def test_the_password_a_caller_supplies_never_appears_in_a_result(sign_in):
    await sign_in(GOOGLE_A)

    result = await server.change_user_password('ada', 'a-secret-password')

    assert 'a-secret-password' not in repr(result)


# --- A refused credential is never left cached -------------------------------


async def test_a_credential_that_cannot_be_replaced_is_dropped(sign_in, django, cache):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.exchange_error = django_client.DjangoAuthError('No account.')

    with pytest.raises(django_client.DjangoAPIError):
        await server.list_signup_users()

    assert cache.get(GOOGLE_A) is None


async def test_a_credential_refused_twice_is_dropped(sign_in, django, cache):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.next_tokens = ['drf-replacement']
    django.rejects.add('drf-replacement')

    with pytest.raises(django_client.DjangoAPIError):
        await server.list_signup_users()

    assert cache.get(GOOGLE_A) is None


async def test_a_dropped_session_is_rebuilt_from_scratch(sign_in, google, django, cache):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.exchange_error = django_client.DjangoAuthError('No account.')
    with pytest.raises(django_client.DjangoAPIError):
        await server.list_signup_users()

    # The next request finds nothing cached and asks Google and Django again, which
    # is what eventually returns a 401 and makes a client sign in afresh.
    calls_before = google.call_count
    django.exchange_error = None
    django.rejects.clear()
    verified = await server.auth._token_validator.verify_token(GOOGLE_A)

    assert google.call_count == calls_before + 1
    assert verified is not None


# --- An unreachable Django ---------------------------------------------------


async def test_a_caller_is_told_to_sign_in_when_django_cannot_be_reached(
    sign_in, django
):
    await sign_in(GOOGLE_A)
    django.rejects.add(f'drf-for-{GOOGLE_A}')
    django.exchange_error = django_client.DjangoAPIError('Could not reach the API.')

    with pytest.raises(django_client.DjangoAPIError) as failure:
        await server.list_signup_users()

    assert 'sign in again' in str(failure.value).lower()


async def test_no_session_is_established_when_django_cannot_be_reached(sign_in, django):
    django.exchange_error = django_client.DjangoAPIError('Could not reach the API.')

    assert await sign_in(GOOGLE_A) is None


# --- A session never outlives the token it was established from --------------


async def test_a_session_expires_with_the_google_token(sign_in, cache, monkeypatch):
    import time as _time

    verified = await sign_in(GOOGLE_A)
    assert cache.get(GOOGLE_A) is not None

    monkeypatch.setattr(_time, 'time', lambda: verified.expires_at + 1)

    assert cache.get(GOOGLE_A) is None


async def test_a_token_with_no_expiry_does_not_inherit_the_full_ceiling(
    cache, verified_google_token
):
    without_expiry = verified_google_token(GOOGLE_A)
    without_expiry.expires_at = None
    cache.set(GOOGLE_A, without_expiry)

    _, expires_at = cache._entries[cache._key(GOOGLE_A)]
    assert expires_at <= time.time() + server.CREDENTIAL_CACHE_FALLBACK_TTL_SECONDS + 1
    assert expires_at < time.time() + server.CREDENTIAL_CACHE_TTL_SECONDS
