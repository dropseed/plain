"""The order bulk_upsert() sends its batches in.

Concurrent callers avoid deadlocking each other by locking rows in the same
order, which only works if a given logical key always produces the same sort
value -- whichever way the caller happened to spell it. And since this runs
before any query, it must never raise.

Unit-level because `conflict_sort_value` isn't public API; the behavior it buys
is covered end-to-end in tests/public/test_bulk_upsert.py.
"""

from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from app.examples.models.forms import FormsExample
from app.examples.models.upsert import UpsertValueKey
from plain.exceptions import ValidationError
from plain.postgres.query import conflict_sort_value

AMOUNT = FormsExample.amount
RATIO = FormsExample.ratio


def test_equal_decimals_sort_together_whatever_their_scale():
    # Postgres numeric holds these equal, so they have to sort to one place --
    # str() alone spells them "1.0" and "1.00".
    assert Decimal("1.0") == Decimal("1.00")
    assert conflict_sort_value(AMOUNT, Decimal("1.0")) == conflict_sort_value(
        AMOUNT, Decimal("1.00")
    )
    # Including the forms an integer can take.
    assert conflict_sort_value(AMOUNT, Decimal(100)) == conflict_sort_value(
        AMOUNT, Decimal("1E+2")
    )
    # And negative zero, which normalize() keeps the sign on.
    assert conflict_sort_value(AMOUNT, Decimal("-0.00")) == conflict_sort_value(
        AMOUNT, Decimal("0.0")
    )


def test_different_decimals_still_sort_apart():
    assert conflict_sort_value(AMOUNT, Decimal("1.0")) != conflict_sort_value(
        AMOUNT, Decimal("1.5")
    )


def test_a_decimal_too_large_to_normalize_does_not_raise():
    # normalize() overflows on this, and the sort must not go down with it.
    # Postgres rejects an exponent this large on write; that is the useful
    # error, so the value passes through un-normalized.
    assert isinstance(conflict_sort_value(AMOUNT, Decimal("1E+999999999")), tuple)


def test_a_non_finite_decimal_is_rejected_before_the_sort_key():
    # DecimalField.to_python refuses NaN and infinity, so they never reach the
    # sort key at all. conflict_sort_value still guards them -- it takes any
    # Field, and `Decimal("sNaN") == 0` raises -- but this is the real path.
    for value in (Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")):
        with pytest.raises(ValidationError):
            conflict_sort_value(AMOUNT, value)


def test_values_with_no_ordering_of_their_own_do_not_raise():
    assert isinstance(conflict_sort_value(RATIO, float("nan")), tuple)
    assert isinstance(
        conflict_sort_value(UpsertValueKey.zone, ZoneInfo("America/Chicago")), tuple
    )
    assert isinstance(conflict_sort_value(UpsertValueKey.blob, memoryview(b"x")), tuple)


def test_json_objects_sort_together_whatever_order_their_keys_were_written_in():
    payload = UpsertValueKey.payload
    assert conflict_sort_value(payload, {"a": 1, "b": 2}) == conflict_sort_value(
        payload, {"b": 2, "a": 1}
    )
    # A non-string object key is valid -- the encoder stringifies it -- and
    # sorting the keys before that encode would compare an int to a str.
    assert isinstance(conflict_sort_value(payload, {1: "a", "2": "b"}), tuple)


def test_a_polymorphic_json_column_never_compares_across_types():
    # A jsonb column can hold an object in one row and a number in the next.
    # Every value canonicalizes to a string first, so sorting a batch of them
    # never puts an int up against a dict.
    payload = UpsertValueKey.payload
    keys = [conflict_sort_value(payload, value) for value in ({"a": 1}, 7, "s", [1, 2])]
    assert {key[0] for key in keys} == {"str"}
    assert len(set(keys)) == 4
    assert len(sorted(keys)) == 4
