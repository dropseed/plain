"""Tests for the admin date-range helpers used by cards and charts."""

from __future__ import annotations

import datetime

import pytest

from plain.admin.dates import DatetimeRange, DatetimeRangeAliases


def _dt(y, m, d, **kw):
    return datetime.datetime(y, m, d, tzinfo=datetime.UTC, **kw)


def test_as_tuple_and_total_days():
    r = DatetimeRange(start=_dt(2024, 1, 1), end=_dt(2024, 1, 4))
    assert r.as_tuple() == (_dt(2024, 1, 1), _dt(2024, 1, 4))
    assert r.total_days() == 3


def test_iter_days_is_inclusive():
    r = DatetimeRange(start=_dt(2024, 1, 1), end=_dt(2024, 1, 3))
    days = list(r.iter_days())
    assert days == [
        datetime.date(2024, 1, 1),
        datetime.date(2024, 1, 2),
        datetime.date(2024, 1, 3),
    ]


def test_contains_checks_bounds():
    r = DatetimeRange(start=_dt(2024, 1, 1), end=_dt(2024, 1, 31))
    assert _dt(2024, 1, 15) in r
    assert _dt(2023, 12, 31) not in r
    assert _dt(2024, 2, 1) not in r


def test_equality_and_hash():
    a = DatetimeRange(start=_dt(2024, 1, 1), end=_dt(2024, 1, 2))
    b = DatetimeRange(start=_dt(2024, 1, 1), end=_dt(2024, 1, 2))
    c = DatetimeRange(start=_dt(2024, 1, 1), end=_dt(2024, 1, 3))
    assert a == b
    assert a != c
    assert hash(a) == hash(b)


def test_from_value_round_trip():
    assert DatetimeRangeAliases.from_value("Today") is DatetimeRangeAliases.TODAY


def test_from_value_rejects_unknown():
    with pytest.raises(ValueError, match="not a valid value"):
        DatetimeRangeAliases.from_value("Some Nonsense Range")


def test_to_range_today_spans_a_single_day():
    r = DatetimeRangeAliases.to_range("Today")
    assert (r.start.hour, r.start.minute, r.start.second) == (0, 0, 0)
    assert (r.end.hour, r.end.minute) == (23, 59)
    assert r.start.date() == r.end.date()
    assert r.total_days() == 0


def test_to_range_accepts_enum_member():
    r = DatetimeRangeAliases.to_range(DatetimeRangeAliases.SINCE_30_DAYS_AGO)
    # "Since 30 days ago" runs from 30 days back through today.
    assert 29 <= r.total_days() <= 30
