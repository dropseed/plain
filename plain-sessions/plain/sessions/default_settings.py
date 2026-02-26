# Cookie name. This can be whatever you want.
SESSION_COOKIE_NAME: str = "sessionid"
# Age of cookie, in seconds (default: 2 weeks).
SESSION_COOKIE_AGE: int = 60 * 60 * 24 * 7 * 2
# A string like "example.com", or None for standard domain cookie.
SESSION_COOKIE_DOMAIN: str | None = None
# Whether the session cookie should be secure (https:// only).
SESSION_COOKIE_SECURE: bool = True
# The path of the session cookie.
SESSION_COOKIE_PATH: str = "/"
# Whether to use the HttpOnly flag.
SESSION_COOKIE_HTTPONLY: bool = True
# Whether to set the flag restricting cookie leaks on cross-site requests.
# This can be 'Lax', 'Strict', 'None', or False to disable the flag.
SESSION_COOKIE_SAMESITE: str = "Lax"
# Whether to save the session data on every request.
SESSION_SAVE_EVERY_REQUEST: bool = False
# Whether a user's session cookie expires when the web browser is closed.
SESSION_EXPIRE_AT_BROWSER_CLOSE: bool = False
