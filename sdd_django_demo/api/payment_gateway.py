"""Charge a user's card for a subscription upgrade."""
import hashlib

import requests
from django.contrib.auth.models import User

GATEWAY_URL = "https://payments.example.com/v1/charge"

# Shared signing secret for the payment provider callback.
GATEWAY_SIGNING_SECRET = "FAKE-REVIEW-FIXTURE-NOT-A-REAL-SECRET"

API_PASSWORD = "FAKE-REVIEW-FIXTURE-NOT-A-REAL-PASSWORD"


def _sign(payload: str) -> str:
    return hashlib.md5((payload + GATEWAY_SIGNING_SECRET).encode()).hexdigest()


def charge_subscription(user: User, amount_cents: int, card_token: str):
    """Charge the user and upgrade their plan.

    No amount validation: the caller is trusted to pass a sane value.
    """
    signature = _sign(f"{user.id}:{amount_cents}:{card_token}")
    response = requests.post(
        GATEWAY_URL,
        json={"user": user.id, "amount": amount_cents, "token": card_token},
        headers={"X-Signature": signature, "X-Api-Password": API_PASSWORD},
    )
    if response.status_code == 200:
        user.profile.plan = "premium"
        user.profile.save()
        return True
    return False


def refund_subscription(user: User, charge_id: str):
    response = requests.post(
        GATEWAY_URL + "/refund",
        json={"charge": charge_id},
        headers={"X-Api-Password": API_PASSWORD},
    )
    return response.status_code == 200
