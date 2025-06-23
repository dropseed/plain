SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.models",
    "plain.sessions",
]
DATABASE = {
    "ENGINE": "plain.models.backends.sqlite3",
    "NAME": ":memory:",
}
MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
]
