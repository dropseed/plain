from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from plain import postgres
from plain.postgres import types
from plain.utils import timezone

__all__ = ["CachedItem", "CachedItemQuerySet"]


class CachedItemQuerySet(postgres.QuerySet["CachedItem"]):
    def expired(self) -> Self:
        return self.filter(expires_at__lt=timezone.now())

    def unexpired(self) -> Self:
        return self.filter(expires_at__gte=timezone.now())

    def forever(self) -> Self:
        return self.filter(expires_at=None)


@postgres.register_model
class CachedItem(postgres.Model):
    key: str = types.CharField(max_length=255)
    value: Any = types.JSONField(required=False, allow_null=True)
    expires_at: datetime | None = types.DateTimeField(required=False, allow_null=True)
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    updated_at: datetime = types.DateTimeField(auto_now=True)

    query: CachedItemQuerySet = CachedItemQuerySet()

    model_options = postgres.Options(
        indexes=[
            postgres.Index(fields=["expires_at"]),
        ],
        constraints=[
            postgres.UniqueConstraint(
                fields=["key"], name="plaincache_cacheditem_unique_key"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.key
