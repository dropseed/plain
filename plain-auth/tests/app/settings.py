SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.sessions",
    "plain.postgres",
    "app.users",
]
MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthMiddleware",
]
AUTH_LOGIN_URL = "login"
