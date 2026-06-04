from __future__ import annotations

from plain import postgres
from plain.postgres import types


class TimestampMixin:
    """Mixin that provides timestamp fields."""

    created_at = types.DateTimeField(create_now=True)
    updated_at = types.DateTimeField(update_now=True)


@postgres.register_model
class MixinTestModel(TimestampMixin, postgres.Model):
    """Model that inherits fields from a mixin."""

    name = types.TextField(max_length=100)

    query: postgres.QuerySet[MixinTestModel] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
    )
