"""URL wiring for the plain.loginlink test app.

Follows the wiring shown in the package README: the request-link form at
``/login`` plus the package's own router (sent / failed / token views)
mounted under ``/loginlink``.
"""

from __future__ import annotations

from plain.auth.views import AuthView
from plain.http import Response
from plain.loginlink.urls import LoginlinkRouter
from plain.loginlink.views import LoginLinkFormView
from plain.urls import Router, include, path
from plain.views import View


class LoginView(LoginLinkFormView):
    template_name = "loginlinkform.html"


class IndexView(View):
    """Default post-login redirect target."""

    def get(self) -> Response:
        return Response("Home")


class WhoamiView(AuthView):
    """Login-gated probe: 200 when authenticated, redirect otherwise."""

    login_required = True

    def get(self) -> Response:
        return Response("ok")


class AppRouter(Router):
    namespace = ""
    urls = [
        path("login", LoginView, name="login"),
        include("loginlink", LoginlinkRouter),
        path("whoami", WhoamiView, name="whoami"),
        path("", IndexView, name="index"),
    ]
