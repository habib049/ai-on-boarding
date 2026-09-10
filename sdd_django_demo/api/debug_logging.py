import json
import re

from django.contrib.auth.models import User


def log_signin_attempt(username, password):
    print(f"Signin attempt: username={username} password={password}")
    User.objects.filter(username=username).exists()
