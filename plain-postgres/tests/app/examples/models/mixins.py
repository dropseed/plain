from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import Field, types


class TimestampMixin:
    """Mixin that provides timestamp fields."""

    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(update_now=True)


@postgres.register_model
class MixinTestModel(TimestampMixin, postgres.Model):
    """Model that inherits fields from a mixin."""

    name: Field[str] = types.TextField(max_length=100)

    model_options = postgres.Options(
        ordering=["-created_at"],
    )
