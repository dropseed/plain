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
from typing import TYPE_CHECKING, Any, overload

from plain.utils.datastructures import MultiValueDict

from .fields import Field

if TYPE_CHECKING:
    from .forms import Form
    from .result import Error, Invalid

__all__ = ["FieldDisplay", "FormDisplay"]


@dataclass(frozen=True)
class FieldDisplay[T]:
    """One field, prepared for rendering.

    Carries what a template needs to draw an input: the field's `name`, the
    `value` to show, the `Error`s attached to it, whether it's `required`,
    and its `choices` (`[]` for a non-choice field).

    Generic over `T`, the field's cleaned value type — `form[ContactForm.email]`
    is `FieldDisplay[str]`, so `field.value` keeps its static type at the
    view→template seam. Attribute-style access (`form.email`) stays
    `FieldDisplay[Any]` because Python's type system can't dispatch attribute
    lookup by literal name without per-form stubs.
    """

    name: str
    value: T
    errors: list[Error]
    required: bool
    choices: list[tuple[Any, Any]]

    @property
    def html_id(self) -> str:
        """The `id`/`for` value pairing the field's input with its label."""
        return f"id_{self.name}"


class FormDisplay[F: Form]:
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

    Generic over the form class `F`: `FormDisplay(ContactForm)` is inferred
    as `FormDisplay[ContactForm]`, so the form class survives the boundary
    that templates and other consumers read through. For per-field static
    typing, index with the field reference — `form[ContactForm.email]` is
    `FieldDisplay[str]`; the loose-typed `form.email` (and `form["email"]`)
    stay `FieldDisplay[Any]`.

    The core types stay render-agnostic — this only ever *reads* a flat
    `Invalid` (or hand-passed errors/values) and exposes it per field.
    """

    def __init__(
        self,
        form_class: type[F],
        invalid: Invalid | None = None,
        *,
        errors: list[Error] | None = None,
        values: dict[str, Any] | None = None,
    ) -> None:
        self._form_class: type[F] = form_class
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
        self._bound: dict[str, FieldDisplay[Any]] = {}
        if self._errors:
            for err in self._errors:
                if err.field is not None and err.field not in self._fields:
                    raise ValueError(
                        f"{self._form_name}: Error references unknown field "
                        f"{err.field!r}. Known fields: {sorted(self._fields)}. "
                        f"Use field=None for form-level errors."
                    )

    @property
    def form_class(self) -> type[F]:
        """The form class this display was built from."""
        return self._form_class

    def _bind(self, name: str) -> FieldDisplay[Any]:
        if name not in self._fields:
            raise KeyError(f"{self._form_name} has no field {name!r}.")
        if name in self._bound:
            return self._bound[name]
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
        bound: FieldDisplay[Any] = FieldDisplay(
            name=name,
            value=value,
            errors=[error for error in self._errors if error.field == name],
            required=field.required,
            choices=field.choices,
        )
        self._bound[name] = bound
        return bound

    def __getattr__(self, name: str) -> FieldDisplay[Any]:
        # Only reached for names not found normally — i.e. field lookups.
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._bind(name)
        except KeyError as exc:
            raise AttributeError(str(exc)) from None

    @overload
    def __getitem__[T](self, key: Field[T]) -> FieldDisplay[T]: ...
    @overload
    def __getitem__(self, key: str) -> FieldDisplay[Any]: ...
    def __getitem__(self, key: Field[Any] | str) -> FieldDisplay[Any]:
        # A Field reference (`ContactForm.email`) carries its declared type,
        # so indexed access here returns a typed FieldDisplay; a string name
        # is the loose-typed escape hatch.
        if isinstance(key, Field):
            return self._bind(key.name)
        return self._bind(key)

    def __contains__(self, key: Field[Any] | str) -> bool:
        """Whether `key` is one of the form's fields — `'email' in form` or
        `ContactForm.email in form`."""
        if isinstance(key, Field):
            return key.name in self._fields
        return key in self._fields

    def __iter__(self) -> Iterator[FieldDisplay[Any]]:
        for name in self._fields:
            yield self._bind(name)

    @property
    def errors(self) -> list[Error]:
        """Form-level errors — those not attached to a single field."""
        return [error for error in self._errors if error.field is None]
