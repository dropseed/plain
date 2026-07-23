"""Static-typing contract for `QuerySet.select()`.

The `assert_type` calls are verified by the type checker, not at runtime — but
the module still has to import cleanly. The `# ty: ignore[...]` markers on the
misuse cases are load-bearing: if `select()` stopped rejecting them, ty would
report the suppression as unused and this file would fail the type check.

Fields flow to precise per-column types. An expression column contributes
`Any`, but the fields around it stay precise — see
`test_mixed_field_and_expression_row`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, assert_type

from app.examples.models.defaults import DefaultsExample as D

from plain.postgres import RowQuerySet
from plain.postgres.functions import Upper


@dataclass
class NameStat:
    name: str
    priority: int


def test_single_column_row_type() -> None:
    result = D.query.select(D.name)
    assert_type(result, RowQuerySet[tuple[str]])


def test_two_column_row_type() -> None:
    result = D.query.select(D.name, D.priority)
    assert_type(result, RowQuerySet[tuple[str, int]])


def test_three_column_row_type() -> None:
    result = D.query.select(D.name, D.priority, D.status)
    assert_type(result, RowQuerySet[tuple[str, int, str]])


def test_nullable_column_flows_to_optional() -> None:
    result = D.query.select(D.name, D.note)
    assert_type(result, RowQuerySet[tuple[str, str | None]])


def test_flat_single_column() -> None:
    result = D.query.select(D.name, flat=True)
    assert_type(result, RowQuerySet[str])


def test_flat_nullable_column() -> None:
    result = D.query.select(D.note, flat=True)
    assert_type(result, RowQuerySet[str | None])


def test_result_type_row_type() -> None:
    result = D.query.select(D.name, D.priority, result_type=NameStat)
    assert_type(result, RowQuerySet[NameStat])


def test_mixed_field_and_expression_row() -> None:
    # An expression column contributes Any, but the field beside it keeps its
    # precise per-column type.
    result = D.query.select(D.priority, Upper("name"))
    assert_type(result, RowQuerySet[tuple[int, Any]])


if TYPE_CHECKING:
    # Type-check only: these assert on values flowing out of a row queryset.
    # They live here (never executed) because iterating / first() / get()
    # would run a real query — the row types are still checked by ty.
    def _iteration_yields_row_type() -> None:
        for row in D.query.select(D.name, D.priority):
            assert_type(row, tuple[str, int])

    def _first_returns_optional_row() -> None:
        row = D.query.select(D.name, D.priority).first()
        assert_type(row, tuple[str, int] | None)

    def _get_returns_row() -> None:
        row = D.query.select(D.name, D.priority).get()
        assert_type(row, tuple[str, int])

    def _flat_iteration_yields_scalar() -> None:
        for value in D.query.select(D.name, flat=True):
            assert_type(value, str)

    # Each of these misuses must be rejected by ty. The ignore markers are
    # load-bearing — remove the rejection and ty flags the suppression as
    # unused.
    def _select_rejects_string_arg() -> None:
        D.query.select("name")  # ty: ignore[no-matching-overload]

    def _select_rejects_flat_with_two_columns() -> None:
        D.query.select(D.name, D.priority, flat=True)  # ty: ignore[no-matching-overload]

    def _select_rejects_flat_with_result_type() -> None:
        D.query.select(  # ty: ignore[no-matching-overload]
            D.name, flat=True, result_type=NameStat
        )
