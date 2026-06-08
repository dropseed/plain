from __future__ import annotations

from datetime import datetime
from uuid import UUID

from plain import postgres
from plain.postgres import Field, types
from plain.utils import timezone

__all__ = ["APIKey"]


@postgres.register_model
class APIKey(postgres.Model):
    uuid: Field[UUID] = types.UUIDField(generate=True)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)
    updated_at: Field[datetime] = types.DateTimeField(create_now=True, update_now=True)
    expires_at: Field[datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )
    last_used_at: Field[datetime | None] = types.DateTimeField(
        required=False, allow_null=True, default=None
    )

    name: Field[str] = types.TextField(max_length=255, required=False)

    token: Field[str] = types.RandomStringField(length=40)

    api_version: Field[str] = types.TextField(max_length=255, required=False)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["uuid"], name="plainapi_apikey_unique_uuid"
            ),
            postgres.UniqueConstraint(
                fields=["token"], name="plainapi_apikey_unique_token"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name or str(self.uuid)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return self.expires_at < timezone.now()
