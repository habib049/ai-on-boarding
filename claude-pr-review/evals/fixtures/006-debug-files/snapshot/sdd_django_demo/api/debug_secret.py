API_SIGNING_SECRET = "sk-hardcoded-super-secret-do-not-commit-123"


def sign_payload(payload):
    return payload + API_SIGNING_SECRET
