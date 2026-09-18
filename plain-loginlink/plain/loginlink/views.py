from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from plain.http import Request


def redirect_to_next_url(request: Request, default: str = "/") -> RedirectResponse:
    """Redirect to the "next" query param, or the default when it's missing,
    empty, or an external URL (which RedirectResponse refuses)."""
    next_url = request.query_params.get("next") or default
    try:
        return RedirectResponse(next_url, status_code=302)
    except ValueError:
        return RedirectResponse(default, status_code=302)


class LoginLinkFormView(AuthView, TemplateView):
    form_class = LoginLinkForm

    # How long a link stays valid, in seconds. Links work for this entire
    # window, so pick a duration you're comfortable handing out.
    link_expires_in: int = 60 * 60

    def sent_url(self, next_url: str | None) -> str:
        url = reverse("loginlink:sent")
        if next_url:
            # Keep the next URL in the query string so the sent view can
            # redirect to it if the page is reloaded while already logged in.
            return f"{url}?next={next_url}"
        return url

    def get(self) -> Response:
        # Redirect if the user is already logged in. The form is never
        # validated on a GET, so "next" comes from the query string.
        if self.user:
            return redirect_to_next_url(self.request)
        return self.render_form(self.form_class)

    def post(self) -> Response:
        result = self.validate_form(self.form_class)
        if isinstance(result, Response):
            return result
        send_login_link(
            email=result.email,
            request=self.request,
            next_url=result.next,
            expires_in=self.link_expires_in,
        )
        return RedirectResponse(self.sent_url(result.next or None), status_code=302)


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
            return RedirectResponse(
                reverse("loginlink:failed") + "?error=expired", status_code=302
            )
        except LoginLinkInvalid:
            return RedirectResponse(
                reverse("loginlink:failed") + "?error=invalid", status_code=302
            )
        except LoginLinkChanged:
            return RedirectResponse(
                reverse("loginlink:failed") + "?error=changed", status_code=302
            )

        login(self.request, user)

        return redirect_to_next_url(self.request, default=self.success_url)
