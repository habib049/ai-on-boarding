import re


def check_password_ok(value):
    if len(value) < 8 or not re.search(r'[A-Za-z]', value) or not re.search(r'\d', value):
        return False
    return True
