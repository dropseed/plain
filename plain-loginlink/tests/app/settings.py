SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"
INSTALLED_PACKAGES = [
    "plain.loginlink",
    "plain.auth",
    "plain.sessions",
    "plain.postgres",
    "plain.html",
    "plain.email",
    "app.users",
]
MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthMiddleware",
]
AUTH_LOGIN_URL = "login"

# In-memory email backend so the `mailoutbox` fixture can capture sent mail.
EMAIL_BACKEND = "plain.email.backends.locmem.EmailBackend"
EMAIL_DEFAULT_FROM = "test@example.com"
