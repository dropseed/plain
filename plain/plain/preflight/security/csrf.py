from plain.runtime import settings

from .. import Warning, register

W003 = Warning(
    "You don't appear to be using Plain's built-in "
    "cross-site request forgery protection via the middleware "
    "('plain.csrf.middleware.CsrfViewMiddleware' is not in your "
    "MIDDLEWARE). Enabling the middleware is the safest approach "
    "to ensure you don't leave any holes.",
    id="security.W003",
)

W016 = Warning(
    "You have 'plain.csrf.middleware.CsrfViewMiddleware' in your "
    "MIDDLEWARE, but you have not set CSRF_COOKIE_SECURE to True. "
    "Using a secure-only CSRF cookie makes it more difficult for network "
    "traffic sniffers to steal the CSRF token.",
    id="security.W016",
)


def _csrf_middleware():
    return "plain.csrf.middleware.CsrfViewMiddleware" in settings.MIDDLEWARE


@register(deploy=True)
def check_csrf_middleware(package_configs, **kwargs):
    passed_check = _csrf_middleware()
    return [] if passed_check else [W003]


@register(deploy=True)
def check_csrf_cookie_secure(package_configs, **kwargs):
    passed_check = (
        settings.CSRF_USE_SESSIONS
        or not _csrf_middleware()
        or settings.CSRF_COOKIE_SECURE is True
    )
    return [] if passed_check else [W016]
