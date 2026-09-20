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
from plain.postgres import Field, RowQuerySet, types
from plain.postgres.expressions import F
from plain.postgres.functions import Upper

from plain import postgres


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
    assert_type(
        D.query.select(D.name, D.priority).get_or_none(), tuple[str, int] | None
    )
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
    assert_type(rows.bulk_update([], ["name"]), Never)
    assert_type(rows.returning(), Never)
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
    assert_type(rows.for_update(), RowQuerySet[tuple[str, int]])
    assert_type(rows & rows, RowQuerySet[tuple[str, int]])
    assert_type(rows.all(), RowQuerySet[tuple[str, int]])


def must_accept_or_keeping_the_row_type() -> None:
    """`__or__` carries the row type too.

    It used to be the one chaining method that couldn't be `Self`: a sliced
    left operand is re-expressed as an id subquery against
    `Meta.base_queryset`, which is a plain `QuerySet` by design. #85 settled
    it with an overload pair and a cast on that branch, so the row type
    survives here like it does everywhere else.
    """
    rows = D.query.select(D.name, D.priority)
    assert_type(rows | rows, RowQuerySet[tuple[str, int]])


def must_accept_a_column_from_another_model_because_the_checker_cannot_see_it() -> None:
    """A column carries its value type but not its *model*.

    `Field[str]` is `Field[str]` whichever model declared it, so nothing here
    distinguishes a column meant for `DefaultsExample.query.select()` from one
    meant for `WidgetTag.query.select()`. This line has to type-check clean --
    that is the whole reason `select()` carries a runtime check instead,
    mirroring `where()`'s in tests/typing/conditions_value_types.py.

    Runtime half:
    tests/public/test_select.py::TestColumnsBelongToTheirModel.
    """
    assert_type(D.query.select(WidgetTag.id), RowQuerySet[tuple[int]])


@postgres.register_model
class ReadmeUser(postgres.Model):
    """The README's lead `select()` example, so it can't rot.

    Mirrors `plain/postgres/README.md`'s "Selecting columns with select()"
    block: the field annotations and the row type it claims have to keep
    type-checking exactly as written there.
    """

    email: Field[str] = types.EmailField()
    age: Field[int | None] = types.IntegerField(allow_null=True, default=None)


def must_accept_the_readme_example() -> None:
    rows = ReadmeUser.query.where(ReadmeUser.age.gte(18)).select(
        ReadmeUser.email, ReadmeUser.age
    )
    assert_type(rows, RowQuerySet[tuple[str, int | None]])
    for email, age in rows:
        assert_type(email, str)
        assert_type(age, int | None)


def must_accept_selecting_after_returning_because_only_runtime_sees_it() -> None:
    """The other order is a runtime-only refusal.

    `select()` after `returning()` raises, but nothing here can say so:
    `ReturningQuerySet` is a `QuerySet` subclass, so `select()` resolves on it
    like any other method. Only the `RowQuerySet` direction is typed (it
    returns `Never`, asserted above). Runtime half:
    tests/public/test_select.py::test_select_after_returning_raises.
    """
    assert_type(D.query.returning().select(D.name), RowQuerySet[tuple[str]])
