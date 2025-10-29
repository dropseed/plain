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
    "app.users",
]


def DEFAULT_RESPONSE_HEADERS(request):
    """
    Strict CSP policy for testing CSP nonce support.
    """
    nonce = request.csp_nonce
    return {
        "Content-Security-Policy": (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            f"style-src 'self' 'nonce-{nonce}'; "
            f"img-src 'self' data: https://www.gravatar.com; "
            f"font-src 'self'; "
            f"connect-src 'self'; "
            f"frame-ancestors 'self'; "
            f"base-uri 'self'; "
            f"form-action 'self'"
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
