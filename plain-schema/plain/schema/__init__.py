"""Validating parsers for typed Python data.

A `Schema` declares fields with `types.*` validators; calling `.validate(data)`
returns either an instance of the schema (with cleaned, typed attributes) or an
`Invalid` carrying per-field errors. Eliminate `Invalid` with `isinstance` to
narrow into the success case without `.data` indirection.

Schemas are pure data — they don't take a request, don't render HTML, don't
save to a database. They work in views, jobs, scripts, tests, anywhere a dict
needs to become typed Python data.

`SchemaForm` (the HTML form-cycle helper) is re-exported here — it's a thin,
dependency-light primitive. `ModelSchema` is *not* re-exported: it pulls in
`plain.postgres`, so import it from its own module to keep a plain
`from plain.schema import Schema` cheap:

    from plain.schema.modelschema import ModelSchema
"""

from __future__ import annotations

from .fields import Field
from .form import SchemaForm
from .result import Invalid
from .schema import Schema

__all__ = (
    "Field",
    "Invalid",
    "Schema",
    "SchemaForm",
)
