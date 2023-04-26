import secrets

SECRET_KEY_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)"


def generate_secret_key():
    return "".join(secrets.choice(SECRET_KEY_CHARS) for i in range(50))
