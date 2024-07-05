from importlib.util import find_spec

AUTH_USER_MODEL: str
AUTH_LOGIN_URL: str

if find_spec("plain.passwords"):
    # Automatically invalidate sessions on password field change,
    # if the plain-passwords is installed. You can change this value
    # if your password field is named differently, or you want
    # to use a different field to invalidate sessions.
    AUTH_USER_SESSION_HASH_FIELD: str = "password"
else:
    AUTH_USER_SESSION_HASH_FIELD: str = ""
