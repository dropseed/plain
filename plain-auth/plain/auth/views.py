from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import urlparse, urlunparse

from plain.http import (
    ForbiddenError403,
    NotFoundError404,
    QueryDict,
    RedirectResponse,
    ResponseBase,
)
from plain.runtime import settings
from plain.sessions.views import SessionView
from plain.urls import reverse
from plain.utils.cache import patch_cache_control
from plain.views import View
from plain.views.exceptions import ResponseException

from .sessions import logout
from .utils import resolve_url

if TYPE_CHECKING:
    from app.users.models import User

try:
    from plain.admin.impersonate import get_request_impersonator
except ImportError:
    get_request_impersonator: Any = None

__all__ = [
    "AuthView",
    "LoginRequired",
    "LogoutView",
    "redirect_to_login",
]


class LoginRequired(Exception):
    def __init__(self, login_url: str | None = None, redirect_field_name: str = "next"):
        self.login_url = login_url or settings.AUTH_LOGIN_URL
        self.redirect_field_name = redirect_field_name


class AuthView(SessionView):
    login_required = False
    admin_required = False  # Implies login_required
    login_url = settings.AUTH_LOGIN_URL

    @cached_property
    def user(self) -> User | None:
        """Get the authenticated user for this request."""
        from .requests import get_request_user

        return get_request_user(self.request)

    def get_template_context(self) -> dict:
        """Add user and impersonator to template context."""
        context = super().get_template_context()
        context["user"] = self.user
        return context

    def check_auth(self) -> None:
        """Raise LoginRequired, ForbiddenError403, or NotFoundError404 when access is denied."""
        if not self.login_required and not self.admin_required:
            return None

        if not self.user:
            raise LoginRequired(login_url=self.login_url)

        if self.admin_required:
            # At this point, we know user is authenticated (from check above)
            # Check if impersonation is active
            if get_request_impersonator:
                if impersonator := get_request_impersonator(self.request):
                    # Impersonators should be able to view admin pages while impersonating.
                    # There's probably never a case where an impersonator isn't admin, but it can be configured.
                    if not impersonator.is_admin:
                        raise ForbiddenError403(
                            "You do not have permission to access this page."
                        )
                    return

            if not self.user.is_admin:
                # Show a 404 so we don't expose admin urls to non-admin users
                raise NotFoundError404()

    def before_request(self) -> None:
        try:
            self.check_auth()
        except LoginRequired as exc:
            self._deny_unauthenticated(exc)

    def _deny_unauthenticated(self, exc: LoginRequired) -> NoReturn:
        if not self.login_url:
            raise ForbiddenError403("Login required") from exc

        path = self.request.build_absolute_uri()
        resolved_login_url = reverse(exc.login_url)
        # If the login url is the same scheme and net location then use
        # the path as the "next" url.
        login_scheme, login_netloc = urlparse(resolved_login_url)[:2]
        current_scheme, current_netloc = urlparse(path)[:2]
        if (not login_scheme or login_scheme == current_scheme) and (
            not login_netloc or login_netloc == current_netloc
        ):
            path = self.request.get_full_path()
        raise ResponseException(
            redirect_to_login(
                path,
                resolved_login_url,
                exc.redirect_field_name,
            )
        ) from exc

    def after_response(self, response: ResponseBase) -> ResponseBase:
        if self.user:
            # Make sure it at least has private as a default
            patch_cache_control(response, private=True)
        return response


class LogoutView(View):
    def post(self) -> RedirectResponse:
        logout(self.request)
        return RedirectResponse("/")


def redirect_to_login(
    next: str, login_url: str | None = None, redirect_field_name: str = "next"
) -> RedirectResponse:
    """
    Redirect the user to the login page, passing the given 'next' page.
    """
    resolved_url = resolve_url(login_url or settings.AUTH_LOGIN_URL)

    login_url_parts = list(urlparse(resolved_url))
    if redirect_field_name:
        querystring = QueryDict(login_url_parts[4], mutable=True)
        querystring[redirect_field_name] = next
        login_url_parts[4] = querystring.urlencode(safe="/")

    return RedirectResponse(str(urlunparse(login_url_parts)), allow_external=True)
