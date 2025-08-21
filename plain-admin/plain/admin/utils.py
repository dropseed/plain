import hashlib


def get_gravatar_url(user):
    """Generate gravatar URL for the given user if they have an email address."""
    if not user or not hasattr(user, "email") or not user.email:
        return None

    # Create hash of email
    email_hash = hashlib.md5(user.email.lower().strip().encode("utf-8")).hexdigest()

    # Return gravatar URL with default identicon fallback
    return f"https://www.gravatar.com/avatar/{email_hash}?s=64&d=identicon"
