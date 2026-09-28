"""The order bulk_upsert() sends its batches in.

Concurrent callers avoid deadlocking each other by locking rows in the same
order, which works only if two callers holding the same logical key render it
the same way -- however each of them happened to spell it. And since comparing
the results is the sort, comparing them must never raise.

Unit-level because `conflict_sort_value` isn't public API; the behavior it buys
is covered end-to-end in tests/public/test_bulk_upsert.py.
"""

import datetime
from decimal import Decimal
from enum import Enum, StrEnum
from zoneinfo import ZoneInfo

import pytest
from app.examples.models.forms import FormsExample
from app.examples.models.upsert import UpsertItem, UpsertValueKey
from plain.exceptions import ValidationError
from plain.postgres.query import conflict_sort_value

AMOUNT = FormsExample.amount
RATIO = FormsExample.ratio
MOMENT = FormsExample.event_datetime
KEY = UpsertItem.key


def sort_value(field, value):
    """Prepare the value the way bulk_upsert() does, then render it."""
    return conflict_sort_value(field, field.get_prep_value(value))


class Shade(StrEnum):
    RED = "red"


class LegacyShade(str, Enum):
    RED = "red"


class Shouty(str):
    def __str__(self) -> str:  # a SafeString-style override
        return "SHOUTY"


def test_str_subclasses_render_as_the_string_the_column_holds():
    # All of these compare equal to "red" and store as "red", so they have to
    # sort as "red" -- str() alone gives "LegacyShade.RED" and "SHOUTY".
    assert Shade.RED == LegacyShade.RED == Shouty("red") == "red"
    for value in (Shade.RED, LegacyShade.RED, Shouty("red"), "red"):
        assert sort_value(KEY, value) == "red"


def test_bytes_and_memoryview_of_the_same_content_render_the_same():
    # str(memoryview) is an address, which differs run to run and between two
    # callers holding the same bytes.
    assert sort_value(UpsertValueKey.blob, memoryview(b"x")) == sort_value(
        UpsertValueKey.blob, b"x"
    )
    assert sort_value(UpsertValueKey.blob, bytearray(b"x")) == sort_value(
        UpsertValueKey.blob, b"x"
    )
    assert "memory at" not in sort_value(UpsertValueKey.blob, memoryview(b"x"))


def test_one_instant_written_at_two_offsets_renders_once():
    # timestamptz stores the instant, so these are one row.
    utc = datetime.datetime(2024, 1, 1, 12, tzinfo=datetime.UTC)
    new_york = datetime.datetime(2024, 1, 1, 7, tzinfo=ZoneInfo("America/New_York"))
    assert utc == new_york
    assert sort_value(MOMENT, utc) == sort_value(MOMENT, new_york)


def test_signed_zeros_render_the_same():
    assert -0.0 == 0.0
    assert sort_value(RATIO, -0.0) == sort_value(RATIO, 0.0)
    assert sort_value(AMOUNT, Decimal("-0.00")) == sort_value(AMOUNT, Decimal("0.0"))


def test_equal_decimals_render_the_same_whatever_their_scale():
    assert Decimal("1.0") == Decimal("1.00")
    assert sort_value(AMOUNT, Decimal("1.0")) == sort_value(AMOUNT, Decimal("1.00"))
    assert sort_value(AMOUNT, Decimal(100)) == sort_value(AMOUNT, Decimal("1E+2"))


def test_different_values_still_render_apart():
    assert sort_value(AMOUNT, Decimal("1.0")) != sort_value(AMOUNT, Decimal("1.5"))
    assert sort_value(KEY, "a") != sort_value(KEY, "b")


def test_a_decimal_too_large_to_normalize_does_not_raise():
    # normalize() overflows on this; Postgres rejects it on write, and that is
    # the error worth surfacing, so the sort leaves it alone.
    assert isinstance(sort_value(AMOUNT, Decimal("1E+999999999")), str)


def test_a_non_finite_decimal_is_rejected_before_the_sort_key():
    # DecimalField.to_python refuses NaN and infinity, so they never reach the
    # sort key. Finding that out before any query is issued is the point.
    for value in (Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity")):
        with pytest.raises(ValidationError):
            sort_value(AMOUNT, value)


def test_values_with_no_ordering_of_their_own_render_and_sort():
    keys = [
        sort_value(RATIO, float("nan")),
        sort_value(UpsertValueKey.zone, ZoneInfo("America/Chicago")),
        sort_value(UpsertValueKey.blob, memoryview(b"x")),
    ]
    assert all(isinstance(key, str) for key in keys)
    assert len(sorted(keys)) == 3


def test_json_objects_render_the_same_whatever_order_their_keys_were_written_in():
    payload = UpsertValueKey.payload
    assert sort_value(payload, {"a": 1, "b": 2}) == sort_value(
        payload, {"b": 2, "a": 1}
    )
    # A non-string object key is valid -- the encoder stringifies it -- and
    # sorting the keys before that encode would compare an int to a str.
    assert isinstance(sort_value(payload, {1: "a", "2": "b"}), str)


def test_a_polymorphic_json_column_sorts_without_comparing_across_types():
    # A jsonb column can hold an object in one row and a number in the next.
    payload = UpsertValueKey.payload
    keys = [sort_value(payload, value) for value in ({"a": 1}, 7, "s", [1, 2])]
    assert all(isinstance(key, str) for key in keys)
    assert len(set(keys)) == 4
    assert len(sorted(keys)) == 4
