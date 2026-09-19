"""`query` is a ClassVar -- a manager reached off the class, not an instance."""

from __future__ import annotations

from typing import assert_type

from app.examples.models.defaults import DefaultsExample
from app.examples.models.querysets import CustomQuerySet, CustomQuerySetModel
from plain.postgres.query import QuerySet


def must_accept_class_access() -> None:
    assert_type(DefaultsExample.query, QuerySet[DefaultsExample])
    # A model that declares its own `query: ClassVar[MyQuerySet]` keeps the
    # custom methods visible.
    assert_type(CustomQuerySetModel.query, CustomQuerySet)


def must_reject_instance_access(row: DefaultsExample) -> None:
    # Runtime half: tests/public/test_manager_assignment.py.
    _ = row.query  # ty: ignore[invalid-attribute-access]
