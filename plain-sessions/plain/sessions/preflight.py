from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import settings


def add_session_cookie_message(message):
    return message + (
        " Using a secure-only session cookie makes it more difficult for "
        "network traffic sniffers to hijack user sessions."
    )


def add_httponly_message(message):
    return message + (
        " Using an HttpOnly session cookie makes it more difficult for "
        "cross-site scripting attacks to hijack user sessions."
    )


def _session_middleware():
    return "plain.sessions.middleware.SessionMiddleware" in settings.MIDDLEWARE


def _session_app():
    return "plain.sessions" in settings.INSTALLED_PACKAGES


@register_check(name="sessions.cookie_secure", deploy=True)
class CheckSessionCookieSecure(PreflightCheck):
    """Ensures SESSION_COOKIE_SECURE is True in production deployment."""

    def run(self):
        if settings.SESSION_COOKIE_SECURE is True:
            return []

        warnings = []
        if _session_app():
            warnings.append(
                PreflightResult(
                    add_session_cookie_message(
                        "You have 'plain.sessions' in your INSTALLED_PACKAGES, "
                        "but you have not set SESSION_COOKIE_SECURE to True."
                    ),
                    id="security.session_cookie_not_secure_app",
                    warning=True,
                )
            )
        if _session_middleware():
            warnings.append(
                PreflightResult(
                    add_session_cookie_message(
                        "You have 'plain.sessions.middleware.SessionMiddleware' "
                        "in your MIDDLEWARE, but you have not set "
                        "SESSION_COOKIE_SECURE to True."
                    ),
                    id="security.session_cookie_not_secure_middleware",
                    warning=True,
                )
            )
        if len(warnings) > 1:
            warnings = [
                PreflightResult(
                    add_session_cookie_message(
                        "SESSION_COOKIE_SECURE is not set to True."
                    ),
                    id="security.session_cookie_not_secure",
                    warning=True,
                )
            ]
        return warnings


@register_check(name="sessions.cookie_httponly", deploy=True)
class CheckSessionCookieHttpOnly(PreflightCheck):
    """Ensures SESSION_COOKIE_HTTPONLY is True in production deployment."""

    def run(self):
        if settings.SESSION_COOKIE_HTTPONLY is True:
            return []

        warnings = []
        if _session_app():
            warnings.append(
                PreflightResult(
                    add_httponly_message(
                        "You have 'plain.sessions' in your INSTALLED_PACKAGES, "
                        "but you have not set SESSION_COOKIE_HTTPONLY to True.",
                    ),
                    id="security.session_cookie_not_httponly_app",
                    warning=True,
                )
            )
        if _session_middleware():
            warnings.append(
                PreflightResult(
                    add_httponly_message(
                        "You have 'plain.sessions.middleware.SessionMiddleware' "
                        "in your MIDDLEWARE, but you have not set "
                        "SESSION_COOKIE_HTTPONLY to True."
                    ),
                    id="security.session_cookie_not_httponly_middleware",
                    warning=True,
                )
            )
        if len(warnings) > 1:
            warnings = [
                PreflightResult(
                    add_httponly_message("SESSION_COOKIE_HTTPONLY is not set to True."),
                    id="security.session_cookie_not_httponly",
                    warning=True,
                )
            ]
        return warnings
