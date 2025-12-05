from __future__ import annotations

from typing import Any

from plain.auth import login, logout
from plain.auth.views import AuthView
from plain.forms import BaseForm
from plain.http import Response, ResponseRedirect
from plain.runtime import settings
from plain.urls import reverse, reverse_lazy
from plain.views import FormView, TemplateView, View

from .forms import LoginLinkForm
from .links import (
    LoginLinkChanged,
    LoginLinkExpired,
    LoginLinkInvalid,
    get_link_token_user,
)


class LoginLinkFormView(AuthView, FormView):
    form_class = LoginLinkForm
    success_url = reverse_lazy("loginlink:sent")

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            form = self.get_form()
            return ResponseRedirect(self.get_success_url(form))

        return super().get()

    def form_valid(self, form: LoginLinkForm) -> Response:  # type: ignore[override]
        form.maybe_send_link(self.request)
        return super().form_valid(form)

    def get_success_url(self, form: BaseForm) -> str:
        if next_url := form.cleaned_data.get("next"):
            # Keep the next URL in the query string so the sent
            # view can redirect to it if reloaded and logged in already.
            return f"{self.success_url}?next={next_url}"
        else:
            return self.success_url


class LoginLinkSentView(AuthView, TemplateView):
    template_name = "loginlink/sent.html"

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            next_url = self.request.query_params.get("next", "/")
            return ResponseRedirect(next_url)

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
            return ResponseRedirect(reverse("loginlink:failed") + "?error=expired")
        except LoginLinkInvalid:
            return ResponseRedirect(reverse("loginlink:failed") + "?error=invalid")
        except LoginLinkChanged:
            return ResponseRedirect(reverse("loginlink:failed") + "?error=changed")

        login(self.request, user)

        if next_url := self.request.query_params.get("next"):
            return ResponseRedirect(next_url)

        return ResponseRedirect(self.success_url)
