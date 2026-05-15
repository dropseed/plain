from __future__ import annotations

from typing import Any

from app.users.models import User

from plain.auth import login, logout
from plain.auth.views import AuthView
from plain.email import TemplateEmail
from plain.http import RedirectResponse, Response
from plain.runtime import settings
from plain.schema import BoundSchema, Invalid
from plain.templates.views import TemplateView
from plain.urls import reverse, reverse_lazy
from plain.views import View

from .links import (
    LoginLinkChanged,
    LoginLinkExpired,
    LoginLinkInvalid,
    generate_link_url,
    get_link_token_user,
)
from .schemas import LoginLinkSchema


class LoginLinkFormView(AuthView, TemplateView):
    schema_class: type[LoginLinkSchema] = LoginLinkSchema
    success_url = reverse_lazy("loginlink:sent")

    # How long an emailed login link stays valid. Override to change it.
    link_expires_in = 60 * 60

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            return RedirectResponse(str(self.success_url))

        return self.render_form(BoundSchema(self.schema_class))

    def post(self) -> Response:
        result = self.schema_class.validate(self.request.form_data)
        if isinstance(result, Invalid):
            return self.render_form(BoundSchema.from_invalid(self.schema_class, result))

        self.maybe_send_link(result)
        return RedirectResponse(self.get_success_url(result))

    def render_form(self, form: BoundSchema) -> Response:
        context = {**self.get_template_context(), "form": form}
        return Response(self.get_template().render(context))

    def get_success_url(self, result: LoginLinkSchema) -> str:
        url = str(self.success_url)  # success_url may be lazy
        if result.next:
            # Keep the next URL in the query string so the sent
            # view can redirect to it if reloaded and logged in already.
            return f"{url}?next={result.next}"
        return url

    def maybe_send_link(self, result: LoginLinkSchema) -> int | None:
        """Email a login link if the address matches a user."""
        try:
            user = User.query.get(email__iexact=result.email)
        except User.DoesNotExist:
            return None

        url = generate_link_url(
            request=self.request,
            user=user,
            email=result.email,
            expires_in=self.link_expires_in,
        )
        if result.next:
            url += f"?next={result.next}"

        email = self.get_template_email(
            email=result.email,
            context={
                "user": user,
                "url": url,
                "expires_in": self.link_expires_in,
            },
        )
        return email.send()

    def get_template_email(
        self, *, email: str, context: dict[str, Any]
    ) -> TemplateEmail:
        return TemplateEmail(
            template="loginlink",
            to=[email],
            context=context,
        )


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
