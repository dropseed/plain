"""Property-based tests verifying schema_strategy() generates inputs that
pass through Schema.validate() cleanly.

Skipped if hypothesis isn't installed — it's an optional dev dependency
since plain.schema.testing is opt-in for users who want property tests.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given, settings  # noqa: E402

from plain.schema import Invalid, Schema, types  # noqa: E402
from plain.schema.testing import schema_strategy  # noqa: E402


class _Wide(Schema):
    """Exercises a broad cross-section of field types."""

    name: str = types.TextField(min_length=2, max_length=50)
    email: str = types.EmailField()
    age: int = types.IntegerField(min_value=0, max_value=150)
    rating: float = types.FloatField(min_value=0.0, max_value=5.0)
    priority: str = types.ChoiceField(
        choices=[("low", "Low"), ("med", "Medium"), ("high", "High")]
    )
    is_active: bool = types.BooleanField()
    when: date = types.DateField()
    started_at: datetime = types.DateTimeField()
    token: UUID = types.UUIDField()


@settings(max_examples=50)
@given(payload=schema_strategy(_Wide))
def test_strategy_always_produces_valid_payload(payload):
    result = _Wide.validate(payload)
    if isinstance(result, Invalid):
        raise AssertionError(
            f"strategy produced an invalid payload: {payload!r} → {result.errors}"
        )


class _WithOptional(Schema):
    title: str = types.TextField(min_length=1)
    notes: str | None = types.TextField(required=False)
    tags: list[str] = types.MultipleChoiceField(
        choices=[("a", "A"), ("b", "B"), ("c", "C")],
        required=False,
    )


@settings(max_examples=50)
@given(payload=schema_strategy(_WithOptional))
def test_strategy_optional_fields_sometimes_omitted_sometimes_included(payload):
    """Optional fields are randomly omitted; either way validation passes."""
    result = _WithOptional.validate(payload)
    assert not isinstance(result, Invalid)


def test_strategy_raises_for_unsupported_field():
    """FileField has no canonical strategy; we surface that explicitly."""

    class _NotSupported(Schema):
        document: object = types.FileField()  # type: ignore[assignment]

    with pytest.raises(NotImplementedError, match="FileField"):
        schema_strategy(_NotSupported)


@settings(max_examples=20)
@given(payload=schema_strategy(_Wide))
def test_strategy_payloads_round_trip_through_apply_to(payload):
    """A strategy-generated payload survives validate → apply_to → access."""
    result = _Wide.validate(payload)
    assert not isinstance(result, Invalid)
    target = result.apply_to(SimpleNamespace())
    assert target.name == result.name
    assert target.priority in {"low", "med", "high"}
