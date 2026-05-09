from __future__ import annotations

from typing import Any

from plain.assets.urls import get_asset_url
from plain.auth.views import AuthView
from plain.http import RedirectResponse, Response
from plain.runtime import settings
from plain.schema import Schema
from plain.utils.module_loading import import_string
from plain.views import SchemaView, View


class SupportSchemaView(AuthView, SchemaView):
    """Render a user-defined Schema selected by URL slug.

    Users register schema classes under ``settings.SUPPORT_FORMS`` keyed
    by slug; the schema class is responsible for declaring fields and
    optionally exposing ``save(user=..., form_slug=...)`` and
    ``notify(entry, user=...)`` methods that the view calls after a
    successful validation.
    """

    template_name = "support/page.html"

    def get_schema_class(self) -> type[Schema]:
        form_slug = self.url_kwargs["form_slug"]
        return import_string(settings.SUPPORT_FORMS[form_slug])

    def get_initial(self) -> dict[str, Any]:
        # Pre-fill email from the logged-in user (matches the previous
        # SupportForm behavior of `self.fields["email"].initial = user.email`).
        if self.user is not None:
            return {"email": self.user.email}
        return {}

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        form_slug = self.url_kwargs["form_slug"]
        context["form_action"] = self.request.build_absolute_uri()
        context["form_template_name"] = f"support/forms/{form_slug}.html"
        context["success_template_name"] = f"support/success/{form_slug}.html"
        context["success"] = self.request.query_params.get("success") == "true"
        return context

    def schema_valid(self, result: Schema) -> Response:
        form_slug = self.url_kwargs["form_slug"]
        # User-defined hooks: optional `save()` returns the entry, optional
        # `notify(entry)` is called afterward. Both receive `user` and
        # `form_slug` as kwargs so the schema can resolve context-dependent
        # state without per-instance kwargs.
        save = getattr(result, "save", None)
        notify = getattr(result, "notify", None)
        entry = save(user=self.user, form_slug=form_slug) if save else None
        if notify and entry is not None:
            notify(entry, user=self.user)
        return super().schema_valid(result)

    def get_success_url(self, result: Schema) -> str:
        # Redirect to the same view and template so we don't have to create
        # two additional views for iframe vs. non-iframe.
        return "?success=true"


class SupportIFrameView(SupportSchemaView):
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
