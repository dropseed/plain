"""`select()` resolves each column to a precise type in the row.

`Field[T]` subclasses `Selectable[T]`, so a field contributes its `T` to the
row tuple; an expression subclasses `Selectable[Any]` and contributes `Any`
without blurring the fields beside it. The overload ladder on
`QuerySet.select()` is what binds those per-column typevars, and `flat=` and
`result_type=` each pick a different rung -- so the ladder is the promise, and
it is asserted statically.

Nothing here runs, so the calls that would issue a real query (iterating,
first(), get()) are written out the same as any other claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, assert_type

from app.examples.models.defaults import DefaultsExample as D
from app.examples.models.relationships import WidgetTag
from plain.postgres import RowQuerySet
from plain.postgres.functions import Upper


@dataclass
class NameStat:
    name: str
    priority: int


def must_accept_fields_as_per_column_types() -> None:
    assert_type(D.query.select(D.name), RowQuerySet[tuple[str]])
    assert_type(D.query.select(D.name, D.priority), RowQuerySet[tuple[str, int]])
    assert_type(
        D.query.select(D.name, D.priority, D.status),
        RowQuerySet[tuple[str, int, str]],
    )


def must_accept_a_nullable_column_as_optional() -> None:
    assert_type(D.query.select(D.name, D.note), RowQuerySet[tuple[str, str | None]])


def must_accept_flat_as_the_bare_column_type() -> None:
    assert_type(D.query.select(D.name, flat=True), RowQuerySet[str])
    assert_type(D.query.select(D.note, flat=True), RowQuerySet[str | None])


def must_accept_result_type_as_the_row_type() -> None:
    assert_type(
        D.query.select(D.name, D.priority, result_type=NameStat),
        RowQuerySet[NameStat],
    )


def must_accept_an_expression_as_any_without_blurring_its_neighbours() -> None:
    # Expressions are Selectable[Any] for now, so only that column goes to Any.
    assert_type(D.query.select(D.priority, Upper("name")), RowQuerySet[tuple[int, Any]])


def must_accept_the_row_type_flowing_out_of_the_queryset() -> None:
    for row in D.query.select(D.name, D.priority):
        assert_type(row, tuple[str, int])
    assert_type(D.query.select(D.name, D.priority).first(), tuple[str, int] | None)
    assert_type(D.query.select(D.name, D.priority).get(), tuple[str, int])
    for value in D.query.select(D.name, flat=True):
        assert_type(value, str)


def must_reject_string_column_names() -> None:
    # Runtime half: tests/public/test_select.py::test_select_rejects_string_argument.
    D.query.select("name")  # ty: ignore[no-matching-overload]


def must_reject_a_relation_reference() -> None:
    # Runtime half: tests/public/test_select.py::test_select_rejects_fk_reference.
    WidgetTag.query.select(WidgetTag.widget)  # ty: ignore[no-matching-overload]


def must_reject_flat_with_more_than_one_column() -> None:
    # flat= has a one-column rung only. Runtime half: test_select.py.
    D.query.select(D.name, D.priority, flat=True)  # ty: ignore[no-matching-overload]


def must_reject_flat_together_with_result_type() -> None:
    # Runtime half:
    # tests/public/test_select.py::test_select_flat_and_result_type_conflict.
    D.query.select(  # ty: ignore[no-matching-overload]
        D.name, flat=True, result_type=NameStat
    )
