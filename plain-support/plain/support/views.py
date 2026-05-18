from __future__ import annotations

from typing import Any

from plain.assets.urls import get_asset_url
from plain.auth.views import AuthView
from plain.http import RedirectResponse, Response
from plain.runtime import settings
from plain.templates.views import TemplateView
from plain.utils.module_loading import import_string
from plain.views import View

from .core import find_user, notify_support
from .forms import SupportForm
from .models import SupportFormEntry


class SupportFormView(AuthView, TemplateView):
    template_name = "support/page.html"

    def get_form_class(self) -> type[SupportForm]:
        form_slug = self.url_kwargs["form_slug"]
        return import_string(settings.SUPPORT_FORMS[form_slug])

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        form_slug = self.url_kwargs["form_slug"]
        context["form_action"] = self.request.build_absolute_uri()
        context["form_template_name"] = f"support/forms/{form_slug}.html"
        context["success_template_name"] = f"support/success/{form_slug}.html"
        context["success"] = self.request.query_params.get("success") == "true"
        return context

    def get(self) -> Response:
        # Pre-fill the email for an authed user; otherwise start blank.
        values: dict[str, str] = {"email": self.user.email} if self.user else {}
        return self.render(errors=[], values=values)

    def post(self) -> Response:
        result = self.get_form_class().validate(
            self.request.form_data, files=self.request.files
        )
        if not result:
            return self.render(errors=result.errors, values=result.raw)
        entry = SupportFormEntry(
            user=self.user or find_user(result.email),
            form_slug=self.url_kwargs["form_slug"],
        )
        result.save(entry)
        notify_support(entry)
        # Redirect to the same view and template so we don't need separate
        # iframe and non-iframe success views.
        return RedirectResponse("?success=true")


class SupportIFrameView(SupportFormView):
    template_name = "support/iframe.html"

    def after_response(self, response: Response) -> Response:
        response = super().after_response(response)
        # X-Frame-Options are typically in DEFAULT_RESPONSE_HEADERS.
        # Set to None to signal the middleware to skip applying this default header.
        # We can't del/pop it because middleware runs after and would add it back.
        response.headers["X-Frame-Options"] = None
        return response


class SupportFormJSView(View):
    def get(self) -> RedirectResponse:
        return RedirectResponse(get_asset_url("support/embed.js"), allow_external=True)
