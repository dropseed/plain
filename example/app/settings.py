SECRET_KEY = "test"
DEBUG = True
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
    "plain.jobs",
    "plain.loginlink",
    "plain.models",
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
    "plain.s3",
    "app.users",
]


DEFAULT_RESPONSE_HEADERS = {
    # Strict CSP policy for testing CSP nonce support
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'nonce-{request.csp_nonce}'; "
        "style-src 'self' 'nonce-{request.csp_nonce}'; "
        "img-src 'self' data: https://www.gravatar.com; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


EMAIL_BACKEND = "plain.email.backends.console.EmailBackend"
EMAIL_DEFAULT_FROM = "from@example.com"
SUPPORT_EMAIL = "support@example.com"
OAUTH_LOGIN_PROVIDERS = {}

MIDDLEWARE = [
    "plain.sessions.middleware.SessionMiddleware",
    "plain.admin.AdminMiddleware",
]

AUTH_LOGIN_URL = "login"
AUTH_USER_MODEL = "users.User"

# S3 connection settings (configure for your storage provider)
S3_ACCESS_KEY_ID = ""
S3_SECRET_ACCESS_KEY = ""
