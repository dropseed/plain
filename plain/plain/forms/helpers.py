"""Typed per-field accessors for a form result.

A view passes the `Form | Invalid` straight to the template; the template
reads each field through these helpers. Each takes a field reference
(`ContactForm.email`) as a second argument, so the type of the cleaned
value rides through `Field[T]` — `field_value(form, ContactForm.email)`
narrows to `str | None` instead of `Any`.

Field metadata (`required`, `choices`, `name`, `html_id`) stays on the
field reference itself — no helper needed for those, just attribute
access on `ContactForm.email`.
"""

from __future__ import annotations

from typing import Any

from plain.utils.datastructures import MultiValueDict

from .fields import Field
from .forms import Form
from .result import Error, Invalid

__all__ = ["field_errors", "field_value", "form_errors"]


def form_errors(form: Form | Invalid) -> list[Error]:
    """Form-level errors — those not attached to a specific field.

    Templates iterate this for cross-field `check()` errors and other
    form-wide messages. Works the same on the success arm of a
    `Form | Invalid` return (empty list) and the failure arm.
    """
    if isinstance(form, Invalid):
        return [e for e in form.errors if e.field is None]
    return []


def field_value[T](form: Form | Invalid, field: Field[T]) -> T | None:
    """Display value for `field` on `form` — cleaned on success, raw on failure.

    Always returns something safe to put in an `<input value=...>`. Typed
    through `Field[T]`: a `Field[str]` gives back `str | None`, a
    `Field[int | None]` gives back `int | None`.
    """
    name = field.name
    if isinstance(form, Invalid):
        raw = form.raw
        if field.multi_value and isinstance(raw, MultiValueDict):
            return raw.getlist(name)  # ty: ignore[invalid-return-type]
        return raw.get(name)
    return getattr(form, name, None)


def field_errors(form: Form | Invalid, field: Field[Any]) -> list[Error]:
    """The list of errors attached to `field`. Empty when there are none."""
    if isinstance(form, Invalid):
        return [e for e in form.errors if e.field == field.name]
    return []
