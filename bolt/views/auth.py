from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import PermissionDenied
from bolt.http import HttpResponse
from bolt.urls import reverse


class LoginRequired(Exception):
    def __init__(self, login_url=None, redirect_field_name="next"):
        self.login_url = login_url or settings.LOGIN_URL
        self.redirect_field_name = redirect_field_name


class AuthViewMixin:
    login_required = True
    staff_required = False
    superuser_required = False
    login_url = None

    def check_auth(self) -> None:
        """
        Raises either LoginRequired or PermissionDenied.
        - LoginRequired can specify a login_url and redirect_field_name
        - PermissionDenied can specify a message
        """

        if not hasattr(self, "request"):
            raise AttributeError(
                "AuthViewMixin requires the request attribute to be set."
            )

        if self.login_required and not self.request.user:
            raise LoginRequired(login_url=self.login_url)

        if self.staff_required and not self.request.user.is_staff:
            # Ideally could customize staff_required_status_code,
            # but we can't set status code with an exception...
            # (404 to hide a private url from non-staff)
            raise PermissionDenied

        if self.superuser_required and not self.request.user.is_superuser:
            raise PermissionDenied

    def get_response(self) -> HttpResponse:
        if not hasattr(self, "request"):
            raise AttributeError(
                "AuthViewMixin requires the request attribute to be set."
            )

        try:
            self.check_auth()
        except LoginRequired as e:
            from bolt.auth.views import redirect_to_login  # Import error on apps not ready
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

        return super().get_response()  # type: ignore
