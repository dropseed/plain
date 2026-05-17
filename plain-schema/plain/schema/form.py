"""`SchemaForm` — the HTML form-cycle primitive for schemas.

A `SchemaForm` pairs a `Schema` with the current request. A view renders it
on GET and calls `.submit()` on POST; `submit()` validates the request's
submitted data and returns the typed schema instance or `Invalid`. On
`Invalid`, the same `SchemaForm` rebinds itself so a re-render shows the
submitted values and per-field errors.

This is the only schema-side view primitive — there is no `SchemaFormView`
base class. A view is a plain `View`/`TemplateView` with explicit `.get()`
and `.post()` that hold and drive a `SchemaForm`. JSON and other non-HTML
surfaces skip `SchemaForm` entirely and call `Schema.validate()` directly.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from plain.exceptions import NON_FIELD_ERRORS

from .result import Invalid
from .schema import Schema

if TYPE_CHECKING:
    from plain.http import Request

    from .fields import Field

__all__ = ("SchemaForm",)


@dataclass
class BoundField:
    """One field of a `SchemaForm`, paired with its display value and errors.

    Obtained by indexing the form with a typed field reference —
    `form[ContactSchema.email]` — or by iterating it. Not constructed
    directly. Templates render the `<input>` themselves; `BoundField` only
    supplies the data: `name`, `value()`, `errors`, and the `field`.
    """

    form: SchemaForm[Any]
    name: str

    @property
    def field(self) -> Field[Any]:
        return self.form.schema_class._schema_fields[self.name]

    def value(self) -> Any:
        """The value to render into the input: the raw submitted value on a
        submitted form (so the user sees what they typed, errors and all),
        the initial value otherwise."""
        if self.form.is_bound:
            raw = self.form.raw
            if self.field.multi_value and hasattr(raw, "getlist"):
                # `raw` has .getlist (verified by the hasattr guard).
                return raw.getlist(self.name)
            return raw.get(self.name)
        if self.name in self.form.initial:
            return self.form.initial[self.name]
        return self.field.initial

    @property
    def errors(self) -> list[str]:
        return self.form.errors.get(self.name, [])


class SchemaForm[S: Schema]:
    """A schema bound to a request — render it, then `submit()` it.

    Construct one in your view, render it on GET, and call `submit()` on
    POST (`TemplateView.render()` takes the context the handler pushes in —
    no `get_template_context()` callback needed):

        class ContactView(TemplateView):
            template_name = "contact.html"

            def schema_form(self):
                return SchemaForm(ContactSchema, self.request)

            def get(self):
                return self.render(form=self.schema_form(), schema=ContactSchema)

            def post(self):
                form = self.schema_form()
                result = form.submit()
                if isinstance(result, Invalid):
                    return self.render(form=form, schema=ContactSchema)
                result.apply_to(ContactSubmission()).save()
                return RedirectResponse("/thanks/")

    `submit()` returns the typed schema instance or `Invalid`; on `Invalid`
    the form rebinds, so passing it back to the template re-renders with the
    submitted values and per-field errors.
    """

    def __init__(
        self,
        schema_class: type[S],
        request: Request,
        *,
        querysets: Mapping[str, Any] | None = None,
        initial: Mapping[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.request = request
        self.initial: dict[str, Any] = dict(initial or {})
        self.context = context
        self.schema_class: type[S] = schema_class
        if querysets:
            # with_querysets() is a ModelSchema method — a non-empty
            # `querysets` implies a ModelSchema-backed form. The scoped
            # subclass drives both rendering and validation, so the
            # `<select>` options and what's accepted stay in lockstep.
            self.schema_class = schema_class.with_querysets(**querysets)  # ty: ignore[unresolved-attribute]
        self.raw: Any = {}
        self.errors: dict[str, list[str]] = {}
        self.is_bound = False

    def submit(self) -> S | Invalid:
        """Validate the request's submitted data against the schema.

        Returns the typed schema instance, or `Invalid`. On `Invalid`, this
        form rebinds itself — a subsequent render shows the submitted values
        and per-field errors. Call it from your `.post()` handler.
        """
        result = self.schema_class.validate(
            self.request.form_data,
            files=self.request.files,
            context=self.context,
        )
        if isinstance(result, Invalid):
            self.raw = result.raw
            self.errors = result.errors
            self.is_bound = True
        return result

    @property
    def fields(self) -> dict[str, Field[Any]]:
        return self.schema_class._schema_fields

    @property
    def non_field_errors(self) -> list[str]:
        return self.errors.get(NON_FIELD_ERRORS, [])

    def __getitem__(self, field: Field[Any]) -> BoundField:
        """Look up one field by its typed reference — `form[ContactSchema.email]`.

        A typo (`ContactSchema.emial`) is an ordinary attribute error, caught
        statically. There is no string-keyed lookup.
        """
        if field.name not in self.schema_class._schema_fields:
            raise KeyError(field.name)
        return BoundField(self, field.name)

    def __iter__(self) -> Iterator[BoundField]:
        for name in self.schema_class._schema_fields:
            yield BoundField(self, name)
