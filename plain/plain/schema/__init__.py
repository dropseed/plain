"""Validating parsers for typed Python data.

A `Schema` declares fields with type annotations and Field validators;
calling `.validate(data)` returns either an instance of the schema (with
cleaned, typed attributes) or an `Invalid` carrying per-field errors.
Eliminate `Invalid` with `isinstance` to narrow into the success case
without `.data` indirection.

Schemas are pure data — they don't take a request, don't render HTML,
don't save to a database. They work in views, jobs, scripts, tests,
anywhere a dict needs to become typed Python data.
"""

from __future__ import annotations

from .bind import BoundField, BoundSchema
from .result import Invalid
from .schema import Schema, make_schema

__all__ = (
    "BoundField",
    "BoundSchema",
    "Invalid",
    "Schema",
    "make_schema",
)
