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

To render a form, a view wraps the outcome in a `FormDisplay` — the opt-in
adapter that gives a template per-field `value` and `errors`. The core types
above stay render-agnostic.

`ModelForm` — a form backed by a model — lives in `plain.postgres`.
"""

from __future__ import annotations

from . import types
from .display import FieldDisplay, FormDisplay
from .fields import Field
from .forms import Form
from .result import Error, Invalid

__all__ = [
    "Error",
    "Field",
    "FieldDisplay",
    "Form",
    "FormDisplay",
    "Invalid",
    "types",
]
