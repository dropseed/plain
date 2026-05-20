from __future__ import annotations

from typing import Any

from plain.auth import login, logout
from plain.auth.views import AuthView
from plain.http import RedirectResponse, Response
from plain.runtime import settings
from plain.templates.views import TemplateView
from plain.urls import reverse
from plain.views import View

from .forms import LoginLinkForm
from .links import (
    LoginLinkChanged,
    LoginLinkExpired,
    LoginLinkInvalid,
    get_link_token_user,
    send_login_link,
)


class LoginLinkFormView(AuthView, TemplateView):
    form_class = LoginLinkForm

    def sent_url(self, next_url: str | None) -> str:
        url = reverse("loginlink:sent")
        if next_url:
            # Keep the next URL in the query string so the sent view can
            # redirect to it if the page is reloaded while already logged in.
            return f"{url}?next={next_url}"
        return url

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            return RedirectResponse(
                self.sent_url(self.request.query_params.get("next"))
            )
        return self.render_form(self.form_class)

    def post(self) -> Response:
        result = self.validate_form(self.form_class)
        if isinstance(result, Response):
            return result
        send_login_link(email=result.email, request=self.request, next_url=result.next)
        return RedirectResponse(self.sent_url(result.next or None))


class LoginLinkSentView(AuthView, TemplateView):
    template_name = "loginlink/sent.html"

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            return RedirectResponse(self.request.query_params.get("next", "/"))

        return super().get()


class LoginLinkFailedView(TemplateView):
    template_name = "loginlink/failed.html"

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["error"] = self.request.query_params.get("error")
        context["login_url"] = reverse(settings.AUTH_LOGIN_URL)
        return context


class LoginLinkLoginView(AuthView, View):
    success_url = "/"

    def get(self) -> Response:
        # If they're logged in, log them out and process the link again
        if self.user:
            logout(self.request)

        token = self.url_kwargs["token"]

        try:
            user = get_link_token_user(token)
        except LoginLinkExpired:
            return RedirectResponse(reverse("loginlink:failed") + "?error=expired")
        except LoginLinkInvalid:
            return RedirectResponse(reverse("loginlink:failed") + "?error=invalid")
        except LoginLinkChanged:
            return RedirectResponse(reverse("loginlink:failed") + "?error=changed")

        login(self.request, user)

        if next_url := self.request.query_params.get("next"):
            return RedirectResponse(next_url)

        return RedirectResponse(self.success_url)
