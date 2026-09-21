from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self

from plain.postgres import Field, types
from plain.runtime import settings
from plain.utils import timezone

from plain import postgres

__all__ = ["CachedItem", "CachedItemQuerySet"]


class CachedItemQuerySet(postgres.QuerySet["CachedItem"]):
    def live(self) -> Self:
        """Rows readable right now: never-expiring *or* not-yet-expired.

        This is the filter cache reads use -- an entry past its `expires_at`
        reads as absent. (Contrast `unexpired()`, which matches only rows with a
        *future* expiry.)
        """
        return self.where(
            CachedItem.expires_at.is_null() | CachedItem.expires_at.gte(timezone.now())
        )

    def expired(self) -> Self:
        return self.where(CachedItem.expires_at.lt(timezone.now()))

    def unexpired(self) -> Self:
        return self.where(CachedItem.expires_at.gte(timezone.now()))

    def forever(self) -> Self:
        return self.where(CachedItem.expires_at.is_null())


@postgres.register_model
class CachedItem(postgres.Model):
    key: Field[str] = types.TextField(max_length=255)
    # `object`, not `Any`: the cache stores any JSON-serializable value, and
    # `Field[Any]` would make `Any` satisfy the model-valued `__get__` overload,
    # so `CachedItem.value` would type as `type[Any]` and lose the field surface
    # entirely.
    value: Field[object] = types.JSONField(
        required=False, allow_null=True, default=None
    )
    expires_at: Field[datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)

    # ClassVar override so @typed doesn't treat it as a constructor field;
    # base Model.query is also a ClassVar, so this override is clean.
    query: ClassVar[CachedItemQuerySet] = CachedItemQuerySet()

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
