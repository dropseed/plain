from __future__ import annotations

import datetime
from typing import Any, Self

from plain.models import (
    CharField,
    DateTimeField,
    Field,
    Index,
    JSONField,
    Model,
    Options,
    QuerySet,
    UniqueConstraint,
    register_model,
)
from plain.utils import timezone


class CachedItemQuerySet(QuerySet["CachedItem"]):
    def expired(self) -> Self:
        return self.filter(expires_at__lt=timezone.now())

    def unexpired(self) -> Self:
        return self.filter(expires_at__gte=timezone.now())

    def forever(self) -> Self:
        return self.filter(expires_at=None)


@register_model
class CachedItem(Model):
    key: Field[str, CharField(max_length=255)]
    value: Field[Any | None, JSONField(allow_null=True)] = None
    expires_at: Field[datetime.datetime | None, DateTimeField(allow_null=True)] = None
    created_at: Field[datetime.datetime | None, DateTimeField(auto_now_add=True)] = None
    updated_at: Field[datetime.datetime | None, DateTimeField(auto_now=True)] = None

    query = CachedItemQuerySet()

    model_options = Options(
        indexes=[
            Index(fields=["expires_at"]),
        ],
        constraints=[
            UniqueConstraint(fields=["key"], name="plaincache_cacheditem_unique_key"),
        ],
    )

    def __str__(self) -> str:
        return self.key
