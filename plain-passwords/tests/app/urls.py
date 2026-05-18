"""URL wiring for the plain.passwords test app.

Each built-in password view is subclassed only to attach the template and
redirect configuration an app is expected to supply (see the package
README). No form behavior is overridden.
"""

from __future__ import annotations

from plain.auth.views import AuthView
from plain.http import Response
from plain.passwords.views import (
    PasswordChangeView,
    PasswordForgotView,
    PasswordLoginView,
    PasswordResetView,
    PasswordSignupView,
)
from plain.urls import Router, path
from plain.views import View


class LoginView(PasswordLoginView):
    template_name = "form.html"
    success_url = "/done"


class SignupView(PasswordSignupView):
    template_name = "form.html"
    success_url = "/done"


class ForgotView(PasswordForgotView):
    template_name = "form.html"
    reset_confirm_url_name = "password_reset"
    success_url = "/done"


class ResetView(PasswordResetView):
    template_name = "form.html"
    success_url = "/done"


class ChangeView(PasswordChangeView):
    template_name = "form.html"
    success_url = "/done"


class DoneView(View):
    """Generic success target for the views above."""

    def get(self) -> Response:
        return Response("Done")


class WhoamiView(AuthView):
    """Login-gated probe: 200 when authenticated, redirect otherwise."""

    login_required = True

    def get(self) -> Response:
        return Response("ok")


class AppRouter(Router):
    namespace = ""
    urls = [
        path("login", LoginView, name="login"),
        path("signup", SignupView, name="signup"),
        path("forgot", ForgotView, name="password_forgot"),
        path("reset", ResetView, name="password_reset"),
        path("change", ChangeView, name="password_change"),
        path("done", DoneView, name="done"),
        path("whoami", WhoamiView, name="whoami"),
    ]
