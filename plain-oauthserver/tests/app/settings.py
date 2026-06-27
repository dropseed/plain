SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.auth",
    "plain.sessions",
    "plain.postgres",
    "plain.templates",
    "plain.oauthserver",
    "app.users",
]
MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
]
AUTH_LOGIN_URL = "login"
OAUTH_SERVER_SCOPES_SUPPORTED = ["read", "offline_access"]
