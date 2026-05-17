"""`SchemaFormView` — the optional view base for the `SchemaForm` GET/POST cycle.

`SchemaForm` is the primitive: any `View`/`TemplateView` can hold one, render
it on GET, and `submit()` it on POST. `SchemaFormView` factors that cycle for
the common case — a subclass declares its `schema_class`, builds its form, and
implements `on_valid()`. Reach for it when a view is *just* a form; write the
handlers by hand on a plain `TemplateView` when it's more (an HTMX action
view, a multi-step flow).

Imported from `plain.schema.views`, not the package top level, so a plain
`from plain.schema import Schema` doesn't load `plain.templates`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from plain.http import Response
from plain.templates.views import TemplateView

from .form import SchemaForm
from .result import Invalid
from .schema import Schema

__all__ = ("SchemaFormView",)


class SchemaFormView[S: Schema](TemplateView, ABC):
    """A `TemplateView` that drives a `SchemaForm` through GET and POST.

    Set `schema_class`, optionally override `get_schema_form()` to scope or
    pre-fill the form (`querysets=`, `initial=`), and implement `on_valid()`.
    The form reaches the template as `form` and the schema class as `schema`;
    add more context by extending `get_template_context()` as usual.
    """

    schema_class: type[S]
    form: SchemaForm[S]

    def get_schema_form(self) -> SchemaForm[S]:
        """Build the form. Override to pass `querysets=` or `initial=`."""
        return SchemaForm(self.schema_class, self.request)

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["schema"] = self.schema_class
        context["form"] = self.form
        return context

    def get(self) -> Response:
        self.form = self.get_schema_form()
        return self.render()

    def post(self) -> Response:
        self.form = self.get_schema_form()
        result = self.form.submit()
        if isinstance(result, Invalid):
            # submit() rebound the form with the submitted values and
            # per-field errors — re-rendering shows them.
            return self.render()
        return self.on_valid(result)

    @abstractmethod
    def on_valid(self, result: S) -> Response:
        """Handle a valid submission — persist, then return a response."""
