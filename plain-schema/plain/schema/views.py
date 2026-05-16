"""Schema-backed views — counterparts to `FormView` and the model CRUD views.

`SchemaFormView` mirrors `FormView`; `SchemaCreateView` / `SchemaUpdateView` /
`SchemaDeleteView` mirror `CreateView` / `UpdateView` / `DeleteView` and are
backed by a `ModelSchema`.

These live in `plain.schema` rather than `plain.templates` on purpose, for
now: while the schema view/render design is still in flux it's easier to
iterate on `Schema`, `BoundSchema`, and the views together in one package.
The trade-off is the dependency on `plain.templates` (and, for the CRUD
views, `plain.postgres` via `ModelSchema`) — once the design settles these
should move to `plain.templates.views` / `plain.postgres`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, get_args, get_origin

from plain.exceptions import ImproperlyConfigured
from plain.http import RedirectResponse, Response
from plain.templates.views import DetailView, TemplateView

from .bind import BoundSchema
from .modelschema import ModelSchema
from .result import Invalid
from .schema import Schema

__all__ = (
    "SchemaFormView",
    "SchemaCreateView",
    "SchemaUpdateView",
    "SchemaDeleteView",
)


class SchemaFormView[S: Schema](TemplateView):
    """A view for displaying a schema-backed form and handling its submission.

    The schema-era counterpart to `FormView`. Generic over the schema type —
    parameterize as `SchemaFormView[MySchema]` for a typed `result` in
    `schema_valid()`. Parameterizing also derives `schema_class` from the
    generic argument, so setting it explicitly is optional.
    """

    schema_class: type[S] | None = None
    success_url: Callable | str | None = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Derive `schema_class` from the generic argument.

            class ContactView(SchemaFormView[ContactSchema]): ...

        sets `schema_class = ContactSchema` with no explicit assignment.
        Skipped if the subclass set `schema_class` itself, or if the generic
        argument is still a type parameter (an intermediate generic base —
        a bare `TypeVar` fails the `isinstance(..., type)` check below).
        """
        super().__init_subclass__(**kwargs)
        if cls.__dict__.get("schema_class") is not None:
            return
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if not (isinstance(origin, type) and issubclass(origin, SchemaFormView)):
                continue
            args = get_args(base)
            if args and isinstance(args[0], type) and issubclass(args[0], Schema):
                cls.schema_class = args[0]
                return

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

    def get_querysets(self) -> Mapping[str, Any]:
        """FK/M2M querysets to scope validation and rendering against.

        Override on a `ModelSchema`-backed view for per-request (multi-tenant)
        scoping — return field-name → queryset, e.g.
        `{"project": Project.query.filter(owner=self.request.user)}`. The
        return is typed `Mapping` so an override may return a stricter
        `ModelSchema.Querysets` TypedDict without an LSP violation.
        """
        return {}

    def _request_schema_class(self) -> type[S]:
        """`get_schema_class()`, narrowed to `get_querysets()` when it returns
        any — so both the rendered `<select>` options and validation are
        scoped to the same per-request querysets."""
        schema_class = self.get_schema_class()
        querysets = self.get_querysets()
        if querysets:
            # Only a ModelSchema exposes with_querysets(); a non-empty
            # get_querysets() implies a ModelSchema-backed view.
            schema_class = schema_class.with_querysets(**querysets)  # ty: ignore[unresolved-attribute]
        return schema_class

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
        """Insert the schema class and a blank bound schema into the context.

        `schema` is the schema class — templates key fields off it,
        `form[schema.email]`; `form` is the `BoundSchema` to render.
        """
        context = super().get_template_context()
        schema_class = self._request_schema_class()
        context["schema"] = schema_class
        context["form"] = BoundSchema(schema_class, initial=self.get_initial())
        return context

    def post(self) -> Response:
        """Validate the POST data; redirect on success, re-render on failure."""
        schema_class = self._request_schema_class()
        result = schema_class.validate(self.request.form_data, files=self.request.files)
        if isinstance(result, Invalid):
            form = BoundSchema.from_invalid(
                schema_class, result, initial=self.get_initial()
            )
            return self.schema_invalid(form)
        return self.schema_valid(result)


def _object_url(success_url: Callable | str | None, obj: Any) -> str:
    """Resolve the post-save redirect for a view holding a created/updated
    `obj`: `success_url` (with `str.format` access to the object's attrs),
    else the object's own `get_absolute_url()`."""
    if success_url:
        return str(success_url).format(**obj.__dict__)
    get_absolute_url = getattr(obj, "get_absolute_url", None)
    if get_absolute_url is None:
        raise ImproperlyConfigured(
            "No URL to redirect to — set success_url, or give the instance a "
            "get_absolute_url() method."
        )
    return get_absolute_url()


class SchemaCreateView[S: ModelSchema](SchemaFormView[S]):
    """`SchemaFormView` for create flows — the `CreateView` counterpart.

    `schema_valid()` calls `result.save(self.get_instance())` to persist a new
    row and stashes it on `self.object`, so `success_url` formatting and
    `get_absolute_url()` can use it.
    """

    object: Any = None

    def get_instance(self) -> Any:
        """The model instance to save the validated values into.

        Default `None` — `ModelSchema.save(None)` builds a fresh instance from
        the schema's `model`. Override to inject values that aren't user
        input, e.g. `return Task(owner=self.user)`.
        """
        return None

    def get_success_url(self, result: S) -> str:
        return _object_url(self.success_url, self.object)

    def schema_valid(self, result: S) -> Response:
        self.object = result.save(self.get_instance())
        return super().schema_valid(result)


class SchemaUpdateView[S: ModelSchema](DetailView, SchemaFormView[S]):
    """`SchemaFormView` for update flows — the `UpdateView` counterpart.

    The form is pre-filled from `self.object` (looked up via the abstract
    `get_object()`) through `ModelSchema.initial_from()`; `schema_valid()`
    applies the validated values back with `result.save(self.object)`.
    """

    def get_initial(self) -> dict[str, Any]:
        return self.get_schema_class().initial_from(self.object)

    def get_success_url(self, result: S) -> str:
        return _object_url(self.success_url, self.object)

    def schema_valid(self, result: S) -> Response:
        result.save(self.object)
        return super().schema_valid(result)


class _EmptyDeleteSchema(Schema):
    """`SchemaDeleteView`'s "form" is just a CSRF-protected confirm
    button, so it carries no fields."""


class SchemaDeleteView(DetailView, SchemaFormView):
    """`SchemaFormView` for delete confirmation — the `DeleteView` counterpart.

    GET renders a confirmation template; POST validates an empty schema and
    `schema_valid()` deletes `self.object`.
    """

    schema_class = _EmptyDeleteSchema

    def schema_valid(self, result: Schema) -> Response:
        self.object.delete()
        return super().schema_valid(result)
