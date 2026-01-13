from __future__ import annotations

from functools import cached_property
from typing import Any
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

from .sessions import logout
from .utils import resolve_url

try:
    from plain.admin.impersonate import get_request_impersonator
except ImportError:
    get_request_impersonator: Any = None


class LoginRequired(Exception):
    def __init__(self, login_url: str | None = None, redirect_field_name: str = "next"):
        self.login_url = login_url or settings.AUTH_LOGIN_URL
        self.redirect_field_name = redirect_field_name


class AuthView(SessionView):
    login_required = False
    admin_required = False  # Implies login_required
    login_url = settings.AUTH_LOGIN_URL

    @cached_property
    def user(self) -> Any | None:
        """Get the authenticated user for this request."""
        from .requests import get_request_user

        return get_request_user(self.request)

    def get_template_context(self) -> dict:
        """Add user and impersonator to template context."""
        context = super().get_template_context()
        context["user"] = self.user
        return context

    def check_auth(self) -> None:
        """
        Raises either LoginRequired or ForbiddenError403.
        - LoginRequired can specify a login_url and redirect_field_name
        - ForbiddenError403 can specify a message
        """
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

    def get_response(self) -> ResponseBase:
        try:
            self.check_auth()
        except LoginRequired as e:
            if self.login_url:
                # Ideally this could be handled elsewhere... like PermissionDenied
                # also seems like this code is used multiple places anyway...
                # could be easier to get redirect query param
                path = self.request.build_absolute_uri()
                resolved_login_url = reverse(e.login_url)
                # If the login url is the same scheme and net location then use the
                # path as the "next" url.
                login_scheme, login_netloc = urlparse(resolved_login_url)[:2]
                current_scheme, current_netloc = urlparse(path)[:2]
                if (not login_scheme or login_scheme == current_scheme) and (
                    not login_netloc or login_netloc == current_netloc
                ):
                    path = self.request.get_full_path()
                return redirect_to_login(
                    path,
                    resolved_login_url,
                    e.redirect_field_name,
                )
            else:
                raise ForbiddenError403("Login required")

        response = super().get_response()

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

    return RedirectResponse(str(urlunparse(login_url_parts)))
