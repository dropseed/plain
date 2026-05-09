from __future__ import annotations

from collections.abc import Callable
from functools import cached_property
from typing import TYPE_CHECKING, Any

from plain.exceptions import ImproperlyConfigured
from plain.http import RedirectResponse, Response
from plain.schema import BoundSchema, Invalid

from .objects import DetailView
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

    def get_validate_context(self) -> dict[str, Any]:
        """Override to supply per-request `context=` to `validate()`.

        Schemas read context for `check()` cross-field validation.
        ModelSchema-backed views typically also override `get_querysets()`
        to scope FK/M2M validation against per-user querysets — those get
        merged into the context automatically.
        """
        querysets = self.get_querysets()
        if querysets:
            return {"querysets": querysets}
        return {}

    def get_querysets(self) -> dict[str, Any]:
        """Override on ModelSchema-backed views to scope FK/M2M validation.

        Returns a dict mapping field names to per-request querysets — e.g.
        `{"project": Project.query.filter(owner=self.user)}`. The default
        `get_validate_context()` merges this under `context["querysets"]`,
        which `ModelSchema.validate` reads to substitute `ModelChoiceField`
        querysets per request.
        """
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
            context=self.get_validate_context(),
        )
        if isinstance(result, Invalid):
            bound = BoundSchema.from_invalid(
                schema_class, result, initial=self.get_initial()
            )
            return self.schema_invalid(bound)
        return self.schema_valid(result)


class SchemaCreateView[S: "Schema"](SchemaView[S]):
    """SchemaView for create-flows — the schema is expected to expose a
    `save()` method that returns the newly-created instance. The view
    stashes that instance on `self.object` so `success_url.format(...)`
    and `instance.get_absolute_url()` work the same way as `CreateView`.
    """

    object: Any = None

    def get_success_url(self, result: S) -> str:
        if self.success_url:
            return str(self.success_url).format(**self.object.__dict__)
        try:
            return self.object.get_absolute_url()
        except AttributeError as exc:
            raise ImproperlyConfigured(
                "No URL to redirect to. Either provide a success_url or "
                "define a get_absolute_url method on the saved instance."
            ) from exc

    def schema_valid(self, result: S) -> Response:
        self.object = result.save()
        return super().schema_valid(result)


class SchemaUpdateView[S: "Schema"](DetailView, SchemaView[S]):
    """SchemaView for update-flows — pre-fills the form from `self.object`
    on GET, applies validated values back to `self.object` on POST via
    `result.save(self.object)`. The base `Schema.save()` method handles
    scalar assignment + persistence; `ModelSchema.save()` additionally
    handles M2M ordering.
    """

    def get_initial(self) -> dict[str, Any]:
        # Pre-fill from the existing instance. BoundField.value() reads
        # by name from this dict before falling back to field.initial.
        return {
            name: getattr(self.object, name, None)
            for name in self.get_schema_class()._schema_fields
        }

    def get_success_url(self, result: S) -> str:
        if self.success_url:
            return str(self.success_url).format(**self.object.__dict__)
        try:
            return self.object.get_absolute_url()
        except AttributeError as exc:
            raise ImproperlyConfigured(
                "No URL to redirect to. Either provide a success_url or "
                "define a get_absolute_url method on the instance."
            ) from exc

    def schema_valid(self, result: S) -> Response:
        result.save(self.object)
        return super().schema_valid(result)


class SchemaDeleteView(DetailView, SchemaView):
    """Confirmation view for deleting `self.object` — uses an empty Schema
    as the form (just a CSRF-protected POST submit, no fields)."""

    @cached_property
    def schema_class(self) -> type[Schema]:
        from plain.schema import Schema

        # Built lazily so this view has no class-level Schema definition.
        return type("EmptyDeleteSchema", (Schema,), {})

    def schema_valid(self, result: Schema) -> Response:
        self.object.delete()
        return super().schema_valid(result)
