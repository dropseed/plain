SECRET_KEY = "test"
URLS_ROUTER = "app.urls.AppRouter"

INSTALLED_PACKAGES = [
    "plain.admin",
    "plain.api",
    "plain.auth",
    "plain.cache",
    "plain.elements",
    "plain.email",
    "plain.flags",
    "plain.htmx",
    "plain.loginlink",
    "plain.models",
    "plain.oauth",
    "plain.pages",
    "plain.pageviews",
    "plain.passwords",
    "plain.sessions",
    "plain.support",
    "plain.tailwind",
    "plain.worker",
    "plain.redirection",
    "app.users",
]

EMAIL_BACKEND = "plain.email.backends.console.EmailBackend"
EMAIL_DEFAULT_FROM = "from@example.com"
SUPPORT_EMAIL = "support@example.com"
OAUTH_LOGIN_PROVIDERS = {}

MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthenticationMiddleware",
    "plain.admin.AdminMiddleware",
]

AUTH_LOGIN_URL = "login"
AUTH_USER_MODEL = "users.User"
