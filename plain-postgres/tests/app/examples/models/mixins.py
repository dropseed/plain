from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import types


class TimestampMixin:
    """Mixin that provides timestamp fields."""

    created_at: datetime = types.DateTimeField(auto_now_add=True)
    updated_at: datetime = types.DateTimeField(auto_now=True)


@postgres.register_model
class MixinTestModel(TimestampMixin, postgres.Model):
    """Model that inherits fields from a mixin."""

    name: str = types.TextField(max_length=100)

    query: postgres.QuerySet[MixinTestModel] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
    )
