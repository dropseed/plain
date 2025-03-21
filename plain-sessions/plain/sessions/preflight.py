from plain.preflight import Warning, register_check
from plain.runtime import settings


def add_session_cookie_message(message):
    return message + (
        " Using a secure-only session cookie makes it more difficult for "
        "network traffic sniffers to hijack user sessions."
    )


W010 = Warning(
    add_session_cookie_message(
        "You have 'plain.sessions' in your INSTALLED_PACKAGES, "
        "but you have not set SESSION_COOKIE_SECURE to True."
    ),
    id="security.W010",
)

W011 = Warning(
    add_session_cookie_message(
        "You have 'plain.sessions.middleware.SessionMiddleware' "
        "in your MIDDLEWARE, but you have not set "
        "SESSION_COOKIE_SECURE to True."
    ),
    id="security.W011",
)

W012 = Warning(
    add_session_cookie_message("SESSION_COOKIE_SECURE is not set to True."),
    id="security.W012",
)


def add_httponly_message(message):
    return message + (
        " Using an HttpOnly session cookie makes it more difficult for "
        "cross-site scripting attacks to hijack user sessions."
    )


W013 = Warning(
    add_httponly_message(
        "You have 'plain.sessions' in your INSTALLED_PACKAGES, "
        "but you have not set SESSION_COOKIE_HTTPONLY to True.",
    ),
    id="security.W013",
)

W014 = Warning(
    add_httponly_message(
        "You have 'plain.sessions.middleware.SessionMiddleware' "
        "in your MIDDLEWARE, but you have not set "
        "SESSION_COOKIE_HTTPONLY to True."
    ),
    id="security.W014",
)

W015 = Warning(
    add_httponly_message("SESSION_COOKIE_HTTPONLY is not set to True."),
    id="security.W015",
)


@register_check(deploy=True)
def check_session_cookie_secure(package_configs, **kwargs):
    if settings.SESSION_COOKIE_SECURE is True:
        return []
    errors = []
    if _session_app():
        errors.append(W010)
    if _session_middleware():
        errors.append(W011)
    if len(errors) > 1:
        errors = [W012]
    return errors


@register_check(deploy=True)
def check_session_cookie_httponly(package_configs, **kwargs):
    if settings.SESSION_COOKIE_HTTPONLY is True:
        return []
    errors = []
    if _session_app():
        errors.append(W013)
    if _session_middleware():
        errors.append(W014)
    if len(errors) > 1:
        errors = [W015]
    return errors


def _session_middleware():
    return "plain.sessions.middleware.SessionMiddleware" in settings.MIDDLEWARE


def _session_app():
    return "plain.sessions" in settings.INSTALLED_PACKAGES
