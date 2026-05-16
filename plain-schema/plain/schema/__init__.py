"""Validating parsers for typed Python data.

A `Schema` declares fields with type annotations and Field validators;
calling `.validate(data)` returns either an instance of the schema (with
cleaned, typed attributes) or an `Invalid` carrying per-field errors.
Eliminate `Invalid` with `isinstance` to narrow into the success case
without `.data` indirection.

Schemas are pure data — they don't take a request, don't render HTML,
don't save to a database. They work in views, jobs, scripts, tests,
anywhere a dict needs to become typed Python data.

`SchemaFormView` and `ModelSchema` are deliberately not re-exported here —
they pull in `plain.templates` and `plain.postgres` respectively. Import
them from their own modules so `from plain.schema import Schema` stays
cheap:

    from plain.schema.views import SchemaFormView
    from plain.schema.modelschema import ModelSchema
"""

from __future__ import annotations

from .bind import BoundField, BoundSchema
from .fields import Field
from .result import Invalid
from .schema import Schema

__all__ = (
    "BoundField",
    "BoundSchema",
    "Field",
    "Invalid",
    "Schema",
)
