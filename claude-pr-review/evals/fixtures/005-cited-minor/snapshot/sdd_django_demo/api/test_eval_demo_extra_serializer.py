from .eval_demo_extra_serializer import SignupSerializer


def test_signup_serializer_accepts_valid_input():
    serializer = SignupSerializer(data={"email": "a@example.com", "password": "longenough"})
    assert serializer.is_valid()
