"""Decide whether a Google access token is one this project will sign someone in with.

Verification, not exchange: the caller completes the Google login itself and sends
the resulting access token here. This project never holds the Google client secret.
"""

import requests
from django.conf import settings

TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'
TOKENINFO_TIMEOUT = 5


class GoogleTokenError(Exception):
    """A token this project will not sign anyone in with."""


def verify_access_token(access_token):
    """Return Google's claims for an access token, or raise GoogleTokenError."""
    try:
        response = requests.get(
            TOKENINFO_URL, params={'access_token': access_token}, timeout=TOKENINFO_TIMEOUT
        )
    except requests.RequestException as err:
        raise GoogleTokenError('Could not reach Google.') from err

    if response.status_code != 200:
        raise GoogleTokenError('Google did not recognise that token.')

    claims = response.json()

    # The audience is the client id the token was minted for. Without this check any
    # other Google application could hand us one of its own users' tokens and be
    # believed.
    if claims.get('aud') not in settings.GOOGLE_OAUTH_CLIENT_IDS:
        raise GoogleTokenError('Token was issued for a different application.')

    # tokeninfo reports this as the string 'true', not a JSON boolean.
    if str(claims.get('email_verified', '')).lower() != 'true':
        raise GoogleTokenError('Google has not verified that address.')

    email = claims.get('email')
    if not email:
        raise GoogleTokenError('Token carries no email address.')

    required_domain = settings.GOOGLE_ALLOWED_HD
    if required_domain and not _matches_hosted_domain(claims, required_domain):
        raise GoogleTokenError('Account is outside the permitted domain.')

    return claims


def _matches_hosted_domain(claims, required_domain):
    """Whether this token's hosted-domain claim satisfies a configured restriction.

    `hd` is Google's own attestation that an account belongs to a Workspace domain;
    the email address's own domain is not the same thing and is never substituted
    for it. If a restriction is configured, only a matching `hd` claim satisfies
    it - a personal Gmail account, or any token with no `hd` at all, does not.
    """
    hosted_domain = claims.get('hd')
    if not hosted_domain:
        return False
    return hosted_domain.lower() == required_domain.lower()
