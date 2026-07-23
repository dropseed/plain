from __future__ import annotations

from typing import Any, Self

from plain import postgres
from plain.postgres import types
from plain.runtime import settings
from plain.utils import timezone

__all__ = ["CachedItem", "CachedItemQuerySet"]


class CachedItemQuerySet(postgres.QuerySet["CachedItem"]):
    def live(self) -> Self:
        """Rows readable right now: never-expiring *or* not-yet-expired.

        This is the filter cache reads use -- an entry past its `expires_at`
        reads as absent. (Contrast `unexpired()`, which matches only rows with a
        *future* expiry.)
        """
        return self.filter(
            postgres.Q(expires_at__isnull=True)
            | postgres.Q(expires_at__gte=timezone.now())
        )

    def expired(self) -> Self:
        return self.filter(expires_at__lt=timezone.now())

    def unexpired(self) -> Self:
        return self.filter(expires_at__gte=timezone.now())

    def forever(self) -> Self:
        return self.filter(expires_at=None)


@postgres.register_model
class CachedItem(postgres.Model):
    key = types.TextField(max_length=255)
    value: Any = types.JSONField(required=False, allow_null=True)
    expires_at = types.DateTimeField(required=False, allow_null=True)
    created_at = types.DateTimeField(create_now=True)
    updated_at = types.DateTimeField(create_now=True, update_now=True)

    query: CachedItemQuerySet = CachedItemQuerySet()

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                name="plaincache_cacheditem_expires_at_idx", fields=["expires_at"]
            ),
        ],
        constraints=[
            postgres.UniqueConstraint(
                fields=["key"], name="plaincache_cacheditem_unique_key"
            ),
        ],
        storage_parameters={
            "autovacuum_vacuum_scale_factor": settings.CACHE_AUTOVACUUM_SCALE_FACTOR,
            "toast.autovacuum_vacuum_scale_factor": settings.CACHE_TOAST_AUTOVACUUM_SCALE_FACTOR,
        },
    )

    def __str__(self) -> str:
        return self.key
