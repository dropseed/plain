from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from plain.exceptions import ImproperlyConfigured
from plain.http import RedirectResponse, Response
from plain.schema import BoundSchema, Invalid

from .templates import TemplateView

if TYPE_CHECKING:
    from plain.schema import Schema


class SchemaView[S: "Schema"](TemplateView):
    """A view for rendering a schema-backed HTML form.

    Parallel to `FormView`, but built on `plain.schema.Schema` + `BoundSchema`
    instead of `plain.forms.Form`. Generic over the schema type — subclasses
    that want type-safe access to their schema should parameterize:
    `SchemaView[MyContactSchema]`.

    The view orchestrates the GET-render / POST-validate / re-render-or-redirect
    cycle. Override `schema_valid()` to act on a successful validation:

        class ContactSchemaView(SchemaView[ContactSchema]):
            schema_class = ContactSchema
            template_name = "contacts/form.html"
            success_url = reverse_lazy("contacts:success")

            def schema_valid(self, result):
                result.apply_to(ContactSubmission()).save()
                return super().schema_valid(result)
    """

    schema_class: type[S] | None = None
    success_url: Callable | str | None = None

    def get_schema_class(self) -> type[S]:
        if not self.schema_class:
            raise ImproperlyConfigured(
                f"No schema class provided. Define "
                f"{self.__class__.__name__}.schema_class or override "
                f"{self.__class__.__name__}.get_schema_class()."
            )
        return self.schema_class

    def get_initial(self) -> dict[str, Any]:
        """Override to supply initial values for the unbound (GET) form."""
        return {}

    def get_success_url(self, result: S) -> str:
        if not self.success_url:
            raise ImproperlyConfigured("No URL to redirect to. Provide a success_url.")
        return str(self.success_url)  # success_url may be lazy

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["form"] = BoundSchema(
            schema_class=self.get_schema_class(),
            initial=self.get_initial(),
        )
        return context

    def schema_valid(self, result: S) -> Response:
        """Called when validation succeeds. Default: redirect to success_url."""
        return RedirectResponse(self.get_success_url(result))

    def schema_invalid(self, bound: BoundSchema) -> Response:
        """Called when validation fails. Default: re-render the template
        with the bound form (raw values + errors)."""
        context = {**self.get_template_context(), "form": bound}
        return Response(self.get_template().render(context))

    def post(self) -> Response:
        schema_class = self.get_schema_class()
        result = schema_class.validate(
            self.request.form_data,
            files=self.request.files,
        )
        if isinstance(result, Invalid):
            bound = BoundSchema.from_invalid(
                schema_class, result, initial=self.get_initial()
            )
            return self.schema_invalid(bound)
        return self.schema_valid(result)
