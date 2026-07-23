from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class FormsExample(postgres.Model):
    """Exercises the ModelForm → POST → save round-trip across a broad
    set of postgres field types. Used by tests/test_modelform_roundtrip.py
    to guard against regressions in modelfield_to_formfield().
    """

    name: Field[str] = types.TextField(max_length=100)
    status: Field[str] = types.TextField(
        max_length=20,
        choices=[("draft", "Draft"), ("published", "Published")],
        default="draft",
    )
    note: Field[str | None] = types.TextField(
        max_length=200, allow_null=True, required=False, default=None
    )
    count: Field[int] = types.IntegerField()
    ratio: Field[float] = types.FloatField()
    amount: Field[Decimal] = types.DecimalField(max_digits=10, decimal_places=2)
    is_active: Field[bool] = types.BooleanField(default=True)
    event_date: Field[date] = types.DateField()
    event_time: Field[time] = types.TimeField()
    event_datetime: Field[datetime] = types.DateTimeField()
    duration: Field[timedelta] = types.DurationField()
    external_id: Field[UUID] = types.UUIDField()
