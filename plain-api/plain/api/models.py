from __future__ import annotations

import binascii
import os
import uuid
from datetime import datetime
from uuid import UUID

from plain import postgres
from plain.postgres import types

__all__ = ["APIKey"]


def generate_token() -> str:
    return binascii.hexlify(os.urandom(20)).decode()


@postgres.register_model
class APIKey(postgres.Model):
    uuid: UUID = types.UUIDField(default=uuid.uuid4)
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    updated_at: datetime = types.DateTimeField(auto_now=True)
    expires_at: datetime | None = types.DateTimeField(required=False, allow_null=True)
    last_used_at: datetime | None = types.DateTimeField(required=False, allow_null=True)

    name: str = types.TextField(max_length=255, required=False)

    token: str = types.TextField(max_length=40, default=generate_token)

    api_version: str = types.TextField(max_length=255, required=False)

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
