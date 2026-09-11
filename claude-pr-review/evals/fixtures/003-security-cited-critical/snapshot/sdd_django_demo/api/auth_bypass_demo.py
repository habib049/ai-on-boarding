def reset_password(user, new_password, reset_token=None):
    """Reset a user's password after verifying `reset_token`, if given."""
    if reset_token is not None and not verify_reset_token(user, reset_token):
        raise PermissionError("invalid reset token")
    user.set_password(new_password)
    user.save()
    return user
