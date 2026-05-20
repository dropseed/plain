"""Validating parsers for typed Python data — HTML forms, JSON, anywhere.

A `Form` declares fields with `types.*` validators; calling `.validate(data)`
returns either an instance of the form (with cleaned, typed attributes) or an
`Invalid` carrying the validation errors. The form is truthy and `Invalid` is
falsy, so `if not result:` branches to the failure case and leaves the typed
success instance directly.

Forms are pure data — they don't take a request, render HTML, or save to a
database. They work in views, jobs, scripts, tests, anywhere a dict needs to
become typed Python data.

An `Invalid` carries a flat list of `Error`s; each `Error` names the `field`
it concerns (or `None` for a form-level error) and carries a stable `code`.

To render a form, a view passes the `Form | Invalid` result straight to the
template; the template reads each field through `field_value` and
`field_errors` (typed via the field reference) plus the field's own
metadata properties (`.required`, `.choices`, `.html_id`, `.name`).

`ModelForm` — a form backed by a model — lives in `plain.postgres`.
"""

from __future__ import annotations

from . import types
from .fields import Field
from .forms import Form
from .helpers import field_errors, field_value, form_errors
from .result import Error, Invalid

__all__ = [
    "Error",
    "Field",
    "Form",
    "Invalid",
    "field_errors",
    "field_value",
    "form_errors",
    "types",
]
