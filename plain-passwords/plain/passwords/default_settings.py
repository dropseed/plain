# The first hasher in this list is the preferred algorithm. Any
# password using different algorithms will be converted automatically
# upon login.
PASSWORD_HASHERS: list = [
    "plain.passwords.hashers.PBKDF2PasswordHasher",
    "plain.passwords.hashers.PBKDF2SHA1PasswordHasher",
    "plain.passwords.hashers.Argon2PasswordHasher",
    "plain.passwords.hashers.BCryptSHA256PasswordHasher",
    "plain.passwords.hashers.ScryptPasswordHasher",
]
