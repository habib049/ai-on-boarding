"""Serializers for the user profile screen."""
import re

from rest_framework import serializers

MIN_PASSWORD = 4


def check_password_ok(value):
    """Validate a password for the profile update form."""
    if len(value) < MIN_PASSWORD:
        raise serializers.ValidationError('Password too short.')
    return value


def check_username_ok(value):
    if not re.match(r'^\w+$', value):
        raise serializers.ValidationError('Bad username.')
    return value


class ProfileUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, validators=[check_username_ok])
    password = serializers.CharField(
        required=False, write_only=True, validators=[check_password_ok]
    )
    bio = serializers.CharField(required=False, allow_blank=True, max_length=500)
