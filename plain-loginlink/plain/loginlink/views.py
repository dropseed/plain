from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.auth import login, logout
from plain.auth.views import AuthView
from plain.http import RedirectResponse, Response
from plain.runtime import settings
from plain.templates.views import FormView, TemplateView
from plain.urls import reverse, reverse_lazy
from plain.views import View

from .forms import LoginLinkForm
from .links import (
    LoginLinkChanged,
    LoginLinkExpired,
    LoginLinkInvalid,
    get_link_token_user,
)

if TYPE_CHECKING:
    from plain.http import Request


def redirect_to_next_url(request: Request, default: str = "/") -> RedirectResponse:
    """Redirect to the "next" query param, or the default when it's missing,
    empty, or an external URL (which RedirectResponse refuses)."""
    next_url = request.query_params.get("next") or default
    try:
        return RedirectResponse(next_url)
    except ValueError:
        return RedirectResponse(default)


class LoginLinkFormView(AuthView, FormView[LoginLinkForm]):
    form_class = LoginLinkForm
    success_url = reverse_lazy("loginlink:sent")

    def get(self) -> Response:
        # Redirect if the user is already logged in. The form is never
        # validated on a GET, so "next" comes from the query string.
        if self.user:
            return redirect_to_next_url(self.request)

        return super().get()

    def form_valid(self, form: LoginLinkForm) -> Response:
        form.maybe_send_link(self.request)
        return super().form_valid(form)

    def get_success_url(self, form: LoginLinkForm) -> str:
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
            return redirect_to_next_url(self.request)

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

        return redirect_to_next_url(self.request, default=self.success_url)
