from __future__ import annotations

from plain import postgres
from plain.postgres import types
from plain.utils import timezone

__all__ = ["APIKey"]


@postgres.register_model
class APIKey(postgres.Model):
    uuid = types.UUIDField(generate=True)
    created_at = types.DateTimeField(create_now=True)
    updated_at = types.DateTimeField(create_now=True, update_now=True)
    expires_at = types.DateTimeField(required=False, allow_null=True)
    last_used_at = types.DateTimeField(required=False, allow_null=True)

    name = types.TextField(max_length=255, required=False)

    token = types.RandomStringField(length=40)

    api_version = types.TextField(max_length=255, required=False)

    query: postgres.QuerySet[APIKey] = postgres.QuerySet()

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
