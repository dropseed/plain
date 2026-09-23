"""Every rung of `select()`'s overload ladder, column by column.

The ladder is ten near-identical overloads, hand-written with no codegen, and
`select_rows.py` only exercised its ends -- one, two, three columns and the
cliff past ten. That left the middle rungs unasserted: transposing two
typevars in the six-column rung type-checked clean, so a wrong row type could
ship silently.

Ten fields with ten *distinct* types is what makes that impossible. A
transposition inside any rung swaps two types in the asserted tuple, and the
`assert_type` fails. Nothing here runs -- the model is never registered at
runtime, because pytest doesn't collect this directory.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import assert_type
from uuid import UUID

from plain.postgres import Field, RowQuerySet, types

from plain import postgres


@postgres.register_model
class TenColumns(postgres.Model):
    c0: Field[str] = types.TextField(max_length=10)
    c1: Field[int] = types.IntegerField(default=0)
    c2: Field[bool] = types.BooleanField(default=False)
    c3: Field[float] = types.FloatField(default=0.0)
    c4: Field[Decimal] = types.DecimalField(max_digits=5, decimal_places=2)
    c5: Field[UUID] = types.UUIDField()
    c6: Field[date] = types.DateField()
    c7: Field[time] = types.TimeField()
    c8: Field[datetime] = types.DateTimeField()
    c9: Field[timedelta] = types.DurationField()


T = TenColumns


def must_accept_rung_one() -> None:
    assert_type(T.query.select(T.c0), RowQuerySet[tuple[str]])


def must_accept_rung_two() -> None:
    assert_type(T.query.select(T.c0, T.c1), RowQuerySet[tuple[str, int]])


def must_accept_rung_three() -> None:
    assert_type(T.query.select(T.c0, T.c1, T.c2), RowQuerySet[tuple[str, int, bool]])


def must_accept_rung_four() -> None:
    assert_type(
        T.query.select(T.c0, T.c1, T.c2, T.c3),
        RowQuerySet[tuple[str, int, bool, float]],
    )


def must_accept_rung_five() -> None:
    assert_type(
        T.query.select(T.c0, T.c1, T.c2, T.c3, T.c4),
        RowQuerySet[tuple[str, int, bool, float, Decimal]],
    )


def must_accept_rung_six() -> None:
    assert_type(
        T.query.select(T.c0, T.c1, T.c2, T.c3, T.c4, T.c5),
        RowQuerySet[tuple[str, int, bool, float, Decimal, UUID]],
    )


def must_accept_rung_seven() -> None:
    assert_type(
        T.query.select(T.c0, T.c1, T.c2, T.c3, T.c4, T.c5, T.c6),
        RowQuerySet[tuple[str, int, bool, float, Decimal, UUID, date]],
    )


def must_accept_rung_eight() -> None:
    assert_type(
        T.query.select(T.c0, T.c1, T.c2, T.c3, T.c4, T.c5, T.c6, T.c7),
        RowQuerySet[tuple[str, int, bool, float, Decimal, UUID, date, time]],
    )


def must_accept_rung_nine() -> None:
    assert_type(
        T.query.select(T.c0, T.c1, T.c2, T.c3, T.c4, T.c5, T.c6, T.c7, T.c8),
        RowQuerySet[tuple[str, int, bool, float, Decimal, UUID, date, time, datetime]],
    )


def must_accept_rung_ten() -> None:
    assert_type(
        T.query.select(T.c0, T.c1, T.c2, T.c3, T.c4, T.c5, T.c6, T.c7, T.c8, T.c9),
        RowQuerySet[
            tuple[str, int, bool, float, Decimal, UUID, date, time, datetime, timedelta]
        ],
    )


def must_accept_the_cliff_past_ten() -> None:
    """An eleventh column has no rung; the *args fallback takes it."""
    from typing import Any

    assert_type(
        T.query.select(
            T.c0, T.c1, T.c2, T.c3, T.c4, T.c5, T.c6, T.c7, T.c8, T.c9, T.c0
        ),
        RowQuerySet[tuple[Any, ...]],
    )
