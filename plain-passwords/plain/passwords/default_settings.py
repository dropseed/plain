# The number of seconds a password reset link is valid for (default: 3 days).
PASSWORD_RESET_TIMEOUT: int = 60 * 60 * 24 * 3

# the first hasher in this list is the preferred algorithm.  any
# password using different algorithms will be converted automatically
# upon login
PASSWORD_HASHERS: list = [
    "plain.passwords.hashers.PBKDF2PasswordHasher",
    "plain.passwords.hashers.PBKDF2SHA1PasswordHasher",
    "plain.passwords.hashers.Argon2PasswordHasher",
    "plain.passwords.hashers.BCryptSHA256PasswordHasher",
    "plain.passwords.hashers.ScryptPasswordHasher",
]
