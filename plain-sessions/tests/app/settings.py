SECRET_KEY = "test"
INSTALLED_PACKAGES = [
    "plain.models",
    "plain.sessions",
]
DATABASES = {
    "default": {
        "ENGINE": "plain.models.backends.sqlite3",
        "NAME": ":memory:",
    }
}
MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
]
