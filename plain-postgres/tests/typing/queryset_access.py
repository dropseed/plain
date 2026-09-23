"""`query` is a ClassVar -- a manager reached off the class, not an instance."""

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


def must_accept_chaining_that_keeps_the_custom_queryset() -> None:
    """A chaining method returns `Self`, not `QuerySet[T]`.

    Anything that clones through `self._chain()` hands back the same class at
    runtime, so annotating it `QuerySet[T]` would erase a custom subclass --
    `CustomQuerySetModel.query.filter(...).get_custom()` would stop
    type-checking even though it works.
    """
    rows = CustomQuerySetModel.query.filter(name="a")
    assert_type(rows, CustomQuerySet)
    assert_type(rows.order_by("name"), CustomQuerySet)
    assert_type(rows.reverse(), CustomQuerySet)
    assert_type(rows.none(), CustomQuerySet)
    assert_type(rows.distinct(), CustomQuerySet)
    assert_type(rows.only("name"), CustomQuerySet)
    assert_type(rows.defer("name"), CustomQuerySet)
    assert_type(rows.for_update(), CustomQuerySet)
    assert_type(rows[0:2], CustomQuerySet)
    assert_type(rows & rows, CustomQuerySet)
    # The custom method stays reachable through the whole chain. (It has no
    # return annotation of its own, so only reachability is claimed here --
    # an unmarked line that started erroring would fail the build.)
    rows.order_by("name").reverse().get_custom()
