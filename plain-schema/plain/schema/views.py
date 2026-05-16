"""`SchemaFormView` — the schema-backed counterpart to `FormView`.

This view lives in `plain.schema` rather than `plain.templates` on purpose,
for now: while the schema view/render design is still in flux it's easier to
iterate on `Schema`, `BoundSchema`, and `SchemaFormView` together in one package.
The trade-off is that `plain.schema` depends on `plain.templates` here — once
the design settles, `SchemaFormView` should move to `plain.templates.views` and
that dependency should go away.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plain.exceptions import ImproperlyConfigured
from plain.http import RedirectResponse, Response
from plain.templates.views import TemplateView

from .bind import BoundSchema
from .result import Invalid
from .schema import Schema

__all__ = ("SchemaFormView",)


class SchemaFormView[S: Schema](TemplateView):
    """A view for displaying a schema-backed form and handling its submission.

    The schema-era counterpart to `FormView`. Generic over the schema type —
    parameterize as `SchemaFormView[MySchema]` for a typed `result` in
    `schema_valid()`. The `schema_class` attribute must still be set.
    """

    schema_class: type[S] | None = None
    success_url: Callable | str | None = None

    def get_schema_class(self) -> type[S]:
        if not self.schema_class:
            raise ImproperlyConfigured(
                f"No schema class provided. Define {self.__class__.__name__}.schema_class "
                f"or override {self.__class__.__name__}.get_schema_class()."
            )
        return self.schema_class

    def get_initial(self) -> dict[str, Any]:
        """Initial values for rendering a blank (or re-rendered) form."""
        return {}

    def get_success_url(self, result: S) -> str:
        """Return the URL to redirect to after a valid submission."""
        if not self.success_url:
            raise ImproperlyConfigured("No URL to redirect to. Provide a success_url.")
        return str(self.success_url)  # success_url may be lazy

    def schema_valid(self, result: S) -> Response:
        """Validation succeeded — redirect to the success URL."""
        return RedirectResponse(self.get_success_url(result))

    def schema_invalid(self, form: BoundSchema) -> Response:
        """Validation failed — re-render the template with the bound schema."""
        context = {**self.get_template_context(), "form": form}
        return Response(self.get_template().render(context))

    def get_template_context(self) -> dict[str, Any]:
        """Insert a blank bound schema into the context as `form`."""
        context = super().get_template_context()
        context["form"] = BoundSchema(
            self.get_schema_class(), initial=self.get_initial()
        )
        return context

    def post(self) -> Response:
        """Validate the POST data; redirect on success, re-render on failure."""
        schema_class = self.get_schema_class()
        result = schema_class.validate(self.request.form_data, files=self.request.files)
        if isinstance(result, Invalid):
            form = BoundSchema.from_invalid(
                schema_class, result, initial=self.get_initial()
            )
            return self.schema_invalid(form)
        return self.schema_valid(result)
