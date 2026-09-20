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
from typing import Any, Never, assert_type

from app.examples.models.defaults import DefaultsExample as D
from app.examples.models.relationships import WidgetTag
from plain.postgres import QuerySet, RowQuerySet
from plain.postgres.expressions import F
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


def must_accept_the_widest_rung_and_fall_back_past_it() -> None:
    """The ladder stops at ten columns; an eleventh degrades to a plain tuple.

    Ten near-identical overloads are hand-written, so both the last rung and
    the cliff past it are asserted -- a transposed typevar in a middle rung
    would otherwise ship silently.
    """
    assert_type(
        D.query.select(
            D.name,
            D.priority,
            D.status,
            D.note,
            D.id,
            D.name,
            D.priority,
            D.status,
            D.note,
            D.id,
        ),
        RowQuerySet[
            tuple[str, int, str, str | None, int, str, int, str, str | None, int]
        ],
    )
    assert_type(
        D.query.select(
            D.name,
            D.priority,
            D.status,
            D.note,
            D.id,
            D.name,
            D.priority,
            D.status,
            D.note,
            D.id,
            D.name,
        ),
        RowQuerySet[tuple[Any, ...]],
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
    # F() is not a BaseExpression, but select() takes it like values_list does.
    # Runtime half: tests/public/test_select.py::test_select_f_expression_column.
    assert_type(D.query.select(D.name, F("priority")), RowQuerySet[tuple[str, Any]])
    assert_type(D.query.select(F("priority"), flat=True), RowQuerySet[Any])


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


def must_accept_row_mode_refusals_as_never_returning() -> None:
    """The row-mode refusals are typed Never, so the checker knows they don't
    return -- a call site's trailing code is unreachable rather than silently
    typed as a QuerySet.

    `Never` on the *return* doesn't reject the call itself; the refusal is
    still a runtime TypeError. Runtime half:
    tests/public/test_select.py::test_values_after_select_raises and friends.
    """
    rows = D.query.select(D.name)
    assert_type(rows.values("name"), Never)
    assert_type(rows.values_list("name"), Never)
    assert_type(rows.get_or_create(name="a"), Never)
    assert_type(rows.prefetch_related("tags"), Never)
    # annotate() appends a column, which would make the declared row type
    # wrong. Runtime half: test_select.py::TestAnnotateAfterSelect.
    assert_type(rows.annotate(n=Upper("name")), Never)


def must_accept_the_row_type_through_iterator_and_chaining() -> None:
    rows = D.query.select(D.name, D.priority)
    assert_type(rows.where(D.priority.gte(1)), RowQuerySet[tuple[str, int]])
    assert_type(rows[0], tuple[str, int])
    assert_type(rows[0:2], RowQuerySet[tuple[str, int]])
    for row in rows.iterator():
        assert_type(row, tuple[str, int])


def must_accept_the_row_type_surviving_every_chaining_method() -> None:
    """`RowQuerySet[R]` specializes its base as `QuerySet[Any]`, so an
    inherited method annotated `QuerySet[T]` would hand back `QuerySet[Any]`
    and drop `R`. They are annotated `Self` instead, which carries it.
    """
    rows = D.query.select(D.name, D.priority)
    assert_type(rows.reverse(), RowQuerySet[tuple[str, int]])
    assert_type(rows.none(), RowQuerySet[tuple[str, int]])
    assert_type(rows.distinct(), RowQuerySet[tuple[str, int]])
    assert_type(rows.order_by("name"), RowQuerySet[tuple[str, int]])
    assert_type(rows.select_for_update(), RowQuerySet[tuple[str, int]])
    assert_type(rows & rows, RowQuerySet[tuple[str, int]])
    assert_type(rows.all(), RowQuerySet[tuple[str, int]])


def must_accept_or_degrading_because_its_clone_can_change_class() -> None:
    """`__or__` is the one chaining method that can't be `Self`.

    A sliced left operand is re-expressed as an id subquery against
    `Meta.base_queryset`, which is a plain `QuerySet` by design -- it must
    never be a user-defined queryset, which might filter rows out. So that
    branch really does hand back a different class, and the annotation says so
    rather than lying.
    """
    rows = D.query.select(D.name, D.priority)
    assert_type(rows | rows, QuerySet[Any])
