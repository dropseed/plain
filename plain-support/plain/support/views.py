from __future__ import annotations

from typing import Any

from plain.assets.urls import get_asset_url
from plain.auth.views import AuthView
from plain.forms import FormDisplay
from plain.html import Markup, Template
from plain.html.views import TemplateView
from plain.http import RedirectResponse, Response
from plain.postgres.forms import create_from
from plain.runtime import settings
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

    def _render_panel(self, *, form: FormDisplay, success: bool) -> Markup:
        # Render the configurable form/success template into a single
        # pre-rendered panel. The set of sub-templates a template includes
        # must be statically knowable, so this dispatch happens here.
        form_slug = self.url_kwargs["form_slug"]
        if success:
            panel_template_name = f"support/success/{form_slug}.html"
        else:
            panel_template_name = f"support/forms/{form_slug}.html"
        panel_context = {
            **self.get_template_context(),
            "form": form,
            "form_action": self.request.build_absolute_uri(),
            "success": success,
        }
        return Markup(Template(panel_template_name).render(panel_context))

    def _shared_context(self, *, form: FormDisplay, success: bool) -> dict[str, Any]:
        return {
            "form": form,
            "form_action": self.request.build_absolute_uri(),
            "success": success,
            "panel": self._render_panel(form=form, success=success),
        }

    def get(self) -> Response:
        # Pre-fill the email for an authed user; otherwise start blank.
        values: dict[str, str] = {"email": self.user.email} if self.user else {}
        form = FormDisplay(self.get_form_class(), values=values)
        success = self.request.query_params.get("success") == "true"
        return self.render(**self._shared_context(form=form, success=success))

    def post(self) -> Response:
        form_class = self.get_form_class()
        result = form_class.validate(self.request.form_data, files=self.request.files)
        if not result:
            return self.render(
                **self._shared_context(
                    form=FormDisplay(form_class, result), success=False
                )
            )
        entry = create_from(
            SupportFormEntry,
            result,
            user=self.user or find_user(result.email),
            form_slug=self.url_kwargs["form_slug"],
        )
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
