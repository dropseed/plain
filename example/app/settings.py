SECRET_KEY = "test"
DEBUG = True
HEALTHCHECK_PATH = "/up/"
URLS_ROUTER = "app.urls.AppRouter"

INSTALLED_PACKAGES = [
    "plain.cloud",
    "plain.admin",
    "plain.api",
    "plain.auth",
    "plain.cache",
    "plain.elements",
    "plain.email",
    "plain.flags",
    "plain.htmx",
    "plain.jobs",
    "plain.loginlink",
    "plain.mcp",
    "plain.postgres",
    "plain.oauth",
    "plain.pages",
    "plain.pageviews",
    "plain.passwords",
    "plain.sessions",
    "plain.support",
    "plain.tailwind",
    "plain.toolbar",
    "plain.redirection",
    "plain.observer",
    "app.users",
    "app.notes",
]


DEFAULT_RESPONSE_HEADERS = {
    # Strict CSP policy for testing CSP nonce support
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'nonce-{request.csp_nonce}'; "
        "style-src 'self' 'nonce-{request.csp_nonce}'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


EMAIL_BACKEND = "plain.email.backends.preview.EmailBackend"
EMAIL_DEFAULT_FROM = "from@example.com"
SUPPORT_EMAIL = "support@example.com"
OAUTH_LOGIN_PROVIDERS = {}

MIDDLEWARE = [
    "plain.postgres.DatabaseConnectionMiddleware",
    "plain.sessions.middleware.SessionMiddleware",
    "plain.auth.middleware.AuthMiddleware",
    "plain.admin.AdminMiddleware",
]

AUTH_LOGIN_URL = "login"
