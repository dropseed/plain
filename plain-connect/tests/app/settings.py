SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.assets",
    "plain.html",
    "plain.toolbar",
    "plain.sessions",
    "plain.auth",
    "plain.postgres",
    "plain.connect",
    "app.users",
]
MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthMiddleware",
]
AUTH_LOGIN_URL = "page"
