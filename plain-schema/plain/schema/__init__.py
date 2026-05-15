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


def __getattr__(name: str) -> Any:
    """Lazy attribute lookup for `UploadedFile` so we don't trigger the
    plain.http import chain at plain.schema module load time."""
    if name == "UploadedFile":
        from plain.internal.files.uploadedfile import UploadedFile

        return UploadedFile
    raise AttributeError(f"module 'plain.schema' has no attribute {name!r}")


__all__ = (
    "BoundField",
    "BoundSchema",
    "Invalid",
    "Schema",
    "UploadedFile",
    "make_schema",
)
