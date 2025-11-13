from __future__ import annotations

from typing import Self

from plain.models import (
    CharField,
    DateTimeField,
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
    key = CharField(max_length=255)
    value = JSONField(required=False, allow_null=True)
    expires_at = DateTimeField(required=False, allow_null=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)

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
