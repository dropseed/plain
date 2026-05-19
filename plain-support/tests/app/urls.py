"""URL wiring for the plain.support test app.

Mounts the package's ``SupportRouter`` (which provides the support form at
``/support/form/<slug>``). A trivial ``login`` route exists only to satisfy
``AUTH_LOGIN_URL``.
"""

from __future__ import annotations

from plain.http import Response
from plain.support.urls import SupportRouter
from plain.urls import Router, include, path
from plain.views import View


class LoginView(View):
    def get(self) -> Response:
        return Response("Login")


class AppRouter(Router):
    namespace = ""
    urls = [
        include("support", SupportRouter),
        path("login", LoginView, name="login"),
    ]
