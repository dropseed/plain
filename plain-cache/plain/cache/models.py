from __future__ import annotations

import datetime
from typing import Any, Self

from plain import models
from plain.utils import timezone


class CachedItemQuerySet(models.QuerySet["CachedItem"]):
    def expired(self) -> Self:
        return self.filter(expires_at__lt=timezone.now())

    def unexpired(self) -> Self:
        return self.filter(expires_at__gte=timezone.now())

    def forever(self) -> Self:
        return self.filter(expires_at=None)


@models.register_model
class CachedItem(models.Model):
    key: str = models.CharField(max_length=255)
    value: Any | None = models.JSONField(required=False, allow_null=True)
    expires_at: datetime.datetime | None = models.DateTimeField(
        required=False, allow_null=True
    )
    created_at: datetime.datetime = models.DateTimeField(auto_now_add=True)
    updated_at: datetime.datetime = models.DateTimeField(auto_now=True)

    query = CachedItemQuerySet()

    model_options = models.Options(
        indexes=[
            models.Index(fields=["expires_at"]),
        ],
        constraints=[
            models.UniqueConstraint(
                fields=["key"], name="plaincache_cacheditem_unique_key"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.key
