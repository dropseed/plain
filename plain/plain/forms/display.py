"""`FormDisplay` — the render-time adapter for a form.

The core (`Form`, `validate`, `Invalid`) is render-agnostic data. A template,
though, wants per-field access: the value to put in each input and that
field's errors. `FormDisplay` is the thin adapter that bridges the two — a
view builds one from the form class and the outcome, and the template walks
it. `plain.forms` itself stays display-free; this is the opt-in layer on top.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from plain.utils.datastructures import MultiValueDict

if TYPE_CHECKING:
    from .fields import Field
    from .forms import Form
    from .result import Error, Invalid

__all__ = ("FieldDisplay", "FormDisplay")


@dataclass(frozen=True)
class FieldDisplay:
    """One field, prepared for rendering.

    Carries what a template needs to draw an input: the field's `name`, the
    `value` to show, the `Error`s attached to it, whether it's `required`,
    and its `choices` (`[]` for a non-choice field).
    """

    name: str
    value: Any
    errors: list[Error]
    required: bool
    choices: list[tuple[Any, Any]]

    @property
    def html_id(self) -> str:
        """The `id`/`for` value pairing the field's input with its label."""
        return f"id_{self.name}"


class FormDisplay:
    """A form prepared for a template.

    A view builds one from the form class plus what to render:

        FormDisplay(ContactForm)                      # blank (GET)
        FormDisplay(ContactForm, values={"email": e}) # blank, pre-filled
        FormDisplay(ContactForm, result)              # a failed validate()
        FormDisplay(ContactForm, errors=[...], values=...)  # a hand-built rejection

    The template then reads each field through one handle:

        {{ form.email.value }}
        {% for error in form.email.errors %}...{% endfor %}
        {% for error in form.errors %}...{% endfor %}   {# form-level #}
        {% for field in form %}...{% endfor %}          {# every field #}

    The core types stay render-agnostic — this only ever *reads* a flat
    `Invalid` (or hand-passed errors/values) and exposes it per field.
    """

    def __init__(
        self,
        form_class: type[Form],
        invalid: Invalid | None = None,
        *,
        errors: list[Error] | None = None,
        values: dict[str, Any] | None = None,
    ) -> None:
        self._fields: dict[str, Field[Any]] = form_class.fields()
        self._form_name = form_class.__name__
        if invalid is not None:
            # The common case — re-rendering a failed validate(). `invalid`
            # already carries both halves, so it wins over errors/values.
            errors = invalid.errors
            values = invalid.raw
        elif values is None:
            # A blank form (a GET) — pre-fill from each field's `initial`.
            values = {
                name: field.initial
                for name, field in self._fields.items()
                if field.initial is not None
            }
        self._errors: list[Error] = errors if errors is not None else []
        self._values: dict[str, Any] = values if values is not None else {}

    def _bind(self, name: str) -> FieldDisplay:
        if name not in self._fields:
            raise KeyError(f"{self._form_name} has no field {name!r}.")
        field = self._fields[name]
        # A multi-value field (multi-select) needs every submitted value, not
        # just the last — pull the list when the source is a multi-valued
        # mapping, as a re-rendered `Invalid.raw` is.
        if field.multi_value and isinstance(self._values, MultiValueDict):
            value: Any = self._values.getlist(name)
        else:
            # A field with no value displays empty — `None` is not text.
            value = self._values.get(name, "")
            if value is None:
                value = ""
        return FieldDisplay(
            name=name,
            value=value,
            errors=[error for error in self._errors if error.field == name],
            required=field.required,
            choices=field.choices,
        )

    def __getattr__(self, name: str) -> FieldDisplay:
        # Only reached for names not found normally — i.e. field lookups.
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._bind(name)
        except KeyError as exc:
            raise AttributeError(str(exc)) from None

    def __getitem__(self, name: str) -> FieldDisplay:
        return self._bind(name)

    def __contains__(self, name: str) -> bool:
        """Whether `name` is one of the form's fields — `'email' in form`."""
        return name in self._fields

    def __iter__(self) -> Iterator[FieldDisplay]:
        for name in self._fields:
            yield self._bind(name)

    @property
    def errors(self) -> list[Error]:
        """Form-level errors — those not attached to a single field."""
        return [error for error in self._errors if error.field is None]
