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

from typing import TYPE_CHECKING, Any

from .bind import BoundField, BoundSchema
from .result import Invalid
from .schema import Schema, make_schema

if TYPE_CHECKING:
    # Re-export for type hints. Importing at runtime triggers a cycle via
    # plain.http → plain.internal.files.uploadhandler → plain.internal.files.uploadedfile.
    from plain.internal.files.uploadedfile import UploadedFile  # noqa: F401

    from .views import SchemaView  # noqa: F401


def __getattr__(name: str) -> Any:
    """Lazy attribute lookup so importing `plain.schema` stays cheap.

    `UploadedFile` would otherwise trigger the plain.http import chain, and
    `SchemaView` would pull in plain.templates — neither belongs in the load
    path of a plain `from plain.schema import Schema`.
    """
    if name == "UploadedFile":
        from plain.internal.files.uploadedfile import UploadedFile

        return UploadedFile
    if name == "SchemaView":
        from .views import SchemaView

        return SchemaView
    raise AttributeError(f"module 'plain.schema' has no attribute {name!r}")


__all__ = (
    "BoundField",
    "BoundSchema",
    "Invalid",
    "Schema",
    "SchemaView",
    "UploadedFile",
    "make_schema",
)
