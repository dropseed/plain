"""Public contract — `plain.forms` field cleaning.

Each field turns one raw value into a typed Python value, or an `Error`. The
`code` on a rejection is part of the contract — code, not message wording, is
what callers and tests match on.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from plain.forms import Field, Form, types


def clean(field: Field[Any], value: Any) -> Any:
    """Validate `{x: value}` against a one-field form; return the cleaned x."""

    class F(Form):
        x = field

    result = F.validate({"x": value})
    assert result, result
    return result.x


def error(field: Field[Any], value: Any):
    """Validate `{x: value}`; return the single `Error` on x."""

    class F(Form):
        x = field

    result = F.validate({"x": value})
    assert not result, f"expected {value!r} to be rejected"
    on_x = [e for e in result.errors if e.field == "x"]
    assert len(on_x) == 1, on_x
    return on_x[0]


class TestTextField:
    def test_cleans_to_str(self):
        assert clean(types.TextField(), "hello") == "hello"

    def test_strips_whitespace_by_default(self):
        assert clean(types.TextField(), "  hi  ") == "hi"

    def test_strip_can_be_disabled(self):
        assert clean(types.TextField(strip=False), "  hi  ") == "  hi  "

    def test_required_by_default(self):
        assert error(types.TextField(), "").code == "required"

    def test_optional_allows_empty(self):
        assert clean(types.TextField(required=False), "") == ""

    def test_max_length(self):
        assert error(types.TextField(max_length=3), "toolong").code == "max_length"

    def test_min_length(self):
        assert error(types.TextField(min_length=5), "hi").code == "min_length"


class TestEmailField:
    def test_valid(self):
        assert clean(types.EmailField(), "a@b.com") == "a@b.com"

    def test_invalid(self):
        assert error(types.EmailField(), "not-an-email").code == "invalid"


class TestURLField:
    def test_valid(self):
        assert clean(types.URLField(), "https://example.com") == "https://example.com"

    def test_invalid(self):
        assert error(types.URLField(), "not a url").code == "invalid"


class TestIntegerField:
    def test_cleans_to_int(self):
        assert clean(types.IntegerField(), "42") == 42

    def test_accepts_trailing_zeros(self):
        # A number input may submit "10.0" — it still means the integer 10.
        assert clean(types.IntegerField(), "10.0") == 10

    def test_non_numeric_rejected(self):
        assert error(types.IntegerField(), "abc").code == "invalid"

    def test_min_value(self):
        assert error(types.IntegerField(min_value=10), "5").code == "min_value"

    def test_max_value(self):
        assert error(types.IntegerField(max_value=10), "50").code == "max_value"

    def test_optional_absent_is_none(self):
        assert clean(types.IntegerField(required=False), "") is None


class TestFloatField:
    def test_cleans_to_float(self):
        assert clean(types.FloatField(), "1.5") == 1.5

    def test_non_numeric_rejected(self):
        assert error(types.FloatField(), "abc").code == "invalid"

    def test_infinity_rejected(self):
        assert error(types.FloatField(), "inf").code == "invalid"


class TestDecimalField:
    def test_cleans_to_decimal(self):
        value = clean(types.DecimalField(), "1.25")
        assert value == Decimal("1.25")
        assert isinstance(value, Decimal)

    def test_non_numeric_rejected(self):
        assert error(types.DecimalField(), "abc").code == "invalid"


class TestBooleanField:
    def test_truthy_string(self):
        assert clean(types.BooleanField(required=False), "on") is True

    def test_false_string_is_false(self):
        assert clean(types.BooleanField(required=False), "false") is False

    def test_zero_string_is_false(self):
        assert clean(types.BooleanField(required=False), "0") is False

    def test_required_means_must_be_true(self):
        # A required BooleanField is a must-tick checkbox.
        assert error(types.BooleanField(), "").code == "required"


class TestNullBooleanField:
    def test_true(self):
        assert clean(types.NullBooleanField(), "true") is True

    def test_false(self):
        assert clean(types.NullBooleanField(), "false") is False

    def test_unrecognized_is_none(self):
        assert clean(types.NullBooleanField(), "") is None


class TestChoiceField:
    choices = [("a", "A"), ("b", "B")]

    def test_valid_choice(self):
        assert clean(types.ChoiceField(choices=self.choices), "a") == "a"

    def test_invalid_choice(self):
        field = types.ChoiceField(choices=self.choices)
        assert error(field, "z").code == "invalid_choice"


class TestMultipleChoiceField:
    choices = [("a", "A"), ("b", "B")]

    def test_valid_subset(self):
        field = types.MultipleChoiceField(choices=self.choices)
        assert clean(field, ["a", "b"]) == ["a", "b"]

    def test_invalid_member(self):
        field = types.MultipleChoiceField(choices=self.choices)
        assert error(field, ["a", "z"]).code == "invalid_choice"


class TestDateField:
    def test_valid(self):
        assert clean(types.DateField(), "2026-05-18") == datetime.date(2026, 5, 18)

    def test_invalid(self):
        assert error(types.DateField(), "not-a-date").code == "invalid"


class TestDateTimeField:
    def test_valid(self):
        assert clean(types.DateTimeField(), "2026-05-18T09:30:00") == datetime.datetime(
            2026, 5, 18, 9, 30
        )

    def test_invalid(self):
        assert error(types.DateTimeField(), "nope").code == "invalid"


class TestTimeField:
    def test_valid(self):
        assert clean(types.TimeField(), "09:30") == datetime.time(9, 30)

    def test_invalid(self):
        assert error(types.TimeField(), "nope").code == "invalid"


class TestDurationField:
    def test_valid(self):
        assert clean(types.DurationField(), "01:30:00") == datetime.timedelta(
            hours=1, minutes=30
        )

    def test_invalid(self):
        assert error(types.DurationField(), "nope").code == "invalid"


class TestUUIDField:
    def test_valid(self):
        text = "12345678-1234-5678-1234-567812345678"
        assert clean(types.UUIDField(), text) == uuid.UUID(text)

    def test_invalid(self):
        assert error(types.UUIDField(), "not-a-uuid").code == "invalid"


class TestJSONField:
    def test_valid(self):
        assert clean(types.JSONField(), '{"a": 1}') == {"a": 1}

    def test_invalid(self):
        assert error(types.JSONField(), "{bad").code == "invalid"
