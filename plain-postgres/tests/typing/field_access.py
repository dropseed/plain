"""Class access yields the typed descriptor; instance access yields the value.

`Field.__get__`'s overloads are what make `Model.field.equals(...)` and
`row.field` both work, and models annotate their fields `Field[T]` -- never
the concrete `TextField[T]` the stub returns -- so `Field[T]` is what the
checker actually sees.
"""

from __future__ import annotations

from typing import assert_type

from app.examples.models.defaults import DefaultsExample
from plain.postgres import Field


def must_accept_class_access_as_the_descriptor() -> None:
    assert_type(DefaultsExample.name, Field[str])
    assert_type(DefaultsExample.note, Field[str | None])
    assert_type(DefaultsExample.priority, Field[int])


def must_accept_instance_access_as_the_value_type(row: DefaultsExample) -> None:
    assert_type(row.name, str)
    assert_type(row.note, str | None)
    assert_type(row.priority, int)


def must_accept_assigning_the_declared_value_type(row: DefaultsExample) -> None:
    row.name = "y"
    row.priority = 99
    row.note = None
    row.note = "set"


def must_reject_assigning_the_wrong_value_type(row: DefaultsExample) -> None:
    # `Field.__set__` takes T. Loosening it to Any (the tempting fix when
    # to_python() converts anyway) would unsuppress all three.
    row.name = 123  # ty: ignore[invalid-assignment]
    row.priority = "no"  # ty: ignore[invalid-assignment]
    # Non-nullable rejects None statically even though the runtime would store
    # it and fail later at validate/save time.
    row.name = None  # ty: ignore[invalid-assignment]
