"""Validating parsers for typed Python data.

A `Schema` declares fields with type annotations and Field validators; calling
`.validate(data)` returns either a `Valid[Self]` (typed cleaned instance) or
an `Invalid` (per-field errors). The two-class union makes type narrowing fall
out of `isinstance` or `match` without asserts.

Schemas are pure data — they don't take a request, don't render HTML, don't
save to a database. They work in views, jobs, scripts, tests, anywhere a dict
needs to become typed Python data.
"""

from __future__ import annotations

from .result import Invalid, Valid
from .schema import Schema, make_schema

__all__ = ("Schema", "Valid", "Invalid", "make_schema")
