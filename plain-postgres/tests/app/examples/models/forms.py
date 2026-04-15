from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

from plain import postgres
from plain.postgres import types


@postgres.register_model
class FormsExample(postgres.Model):
    """Exercises the ModelForm → POST → save round-trip across a broad
    set of postgres field types. Used by tests/test_modelform_roundtrip.py
    to guard against regressions in modelfield_to_formfield().
    """

    name: str = types.TextField(max_length=100)
    status: str = types.TextField(
        max_length=20,
        choices=[("draft", "Draft"), ("published", "Published")],
        default="draft",
    )
    note: str | None = types.TextField(max_length=200, allow_null=True, required=False)
    count: int = types.IntegerField()
    ratio: float = types.FloatField()
    amount: Decimal = types.DecimalField(max_digits=10, decimal_places=2)
    is_active: bool = types.BooleanField(default=True)
    event_date: datetime.date = types.DateField()
    event_time: datetime.time = types.TimeField()
    event_datetime: datetime.datetime = types.DateTimeField()
    duration: datetime.timedelta = types.DurationField()
    external_id: uuid.UUID = types.UUIDField()

    query: postgres.QuerySet[FormsExample] = postgres.QuerySet()
