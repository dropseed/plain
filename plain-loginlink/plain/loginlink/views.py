from __future__ import annotations

from typing import Any

from plain.auth import login, logout
from plain.auth.views import AuthView
from plain.http import RedirectResponse, Response
from plain.runtime import settings
from plain.urls import reverse, reverse_lazy
from plain.views import SchemaView, TemplateView, View

from .forms import LoginLinkSchema
from .links import (
    LoginLinkChanged,
    LoginLinkExpired,
    LoginLinkInvalid,
    get_link_token_user,
)


class LoginLinkSchemaView(AuthView, SchemaView[LoginLinkSchema]):
    schema_class = LoginLinkSchema
    success_url = reverse_lazy("loginlink:sent")

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            return RedirectResponse(str(self.success_url))

        return super().get()

    def schema_valid(self, result: LoginLinkSchema) -> Response:
        result.maybe_send_link(self.request)
        if result.next:
            # Keep the next URL in the query string so the sent
            # view can redirect to it if reloaded and logged in already.
            return RedirectResponse(f"{self.success_url}?next={result.next}")
        return super().schema_valid(result)


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
