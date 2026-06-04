from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class FormsExample(postgres.Model):
    """A broad spread of postgres field types — exercises `model_field`
    derivation across field kinds in tests/public/test_modelform.py.
    """

    name = types.TextField(max_length=100)
    status = types.TextField(
        max_length=20,
        choices=[("draft", "Draft"), ("published", "Published")],
        default="draft",
    )
    note = types.TextField(max_length=200, allow_null=True, required=False)
    count = types.IntegerField()
    ratio = types.FloatField()
    amount = types.DecimalField(max_digits=10, decimal_places=2)
    is_active = types.BooleanField(default=True)
    event_date = types.DateField()
    event_time = types.TimeField()
    event_datetime = types.DateTimeField()
    duration = types.DurationField()
    external_id = types.UUIDField()

    query: postgres.QuerySet[FormsExample] = postgres.QuerySet()
