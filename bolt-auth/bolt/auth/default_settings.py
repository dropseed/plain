##################
# AUTHENTICATION #
##################

AUTH_USER_MODEL = "auth.User"

AUTHENTICATION_BACKENDS = ["bolt.auth.backends.ModelBackend"]

LOGIN_URL = "/accounts/login/"

LOGIN_REDIRECT_URL = "/accounts/profile/"

LOGOUT_REDIRECT_URL = None

# The number of seconds a password reset link is valid for (default: 3 days).
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 3

# the first hasher in this list is the preferred algorithm.  any
# password using different algorithms will be converted automatically
# upon login
PASSWORD_HASHERS = [
    "bolt.auth.hashers.PBKDF2PasswordHasher",
    "bolt.auth.hashers.PBKDF2SHA1PasswordHasher",
    "bolt.auth.hashers.Argon2PasswordHasher",
    "bolt.auth.hashers.BCryptSHA256PasswordHasher",
    "bolt.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = []
