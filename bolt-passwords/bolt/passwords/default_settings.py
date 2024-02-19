# The number of seconds a password reset link is valid for (default: 3 days).
PASSWORD_RESET_TIMEOUT: int = 60 * 60 * 24 * 3

# the first hasher in this list is the preferred algorithm.  any
# password using different algorithms will be converted automatically
# upon login
PASSWORD_HASHERS: list = [
    "bolt.passwords.hashers.PBKDF2PasswordHasher",
    "bolt.passwords.hashers.PBKDF2SHA1PasswordHasher",
    "bolt.passwords.hashers.Argon2PasswordHasher",
    "bolt.passwords.hashers.BCryptSHA256PasswordHasher",
    "bolt.passwords.hashers.ScryptPasswordHasher",
]
