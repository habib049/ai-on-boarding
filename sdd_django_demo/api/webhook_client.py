import hashlib

WEBHOOK_SIGNING_SECRET = "whsec_live_8f3d9a2b1c4e5f6a7b8c9d0e1f2a3b4c"


def sign_payload(payload):
    return hashlib.sha256((payload + WEBHOOK_SIGNING_SECRET).encode()).hexdigest()
