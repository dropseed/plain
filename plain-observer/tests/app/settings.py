SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.sessions",
    "plain.models",
    "plain.htmx",
    "plain.tailwind",
    "plain.admin",
    "app.users",
]
DATABASES = {
    "default": {
        "ENGINE": "plain.models.backends.sqlite3",
        "NAME": ":memory:",
    }
}
MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
    "plain.admin.AdminMiddleware",
]
AUTH_LOGIN_URL = "login"
AUTH_USER_MODEL = "users.User"
