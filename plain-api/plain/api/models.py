import binascii
import os
import uuid
from datetime import datetime
from uuid import UUID

from plain import models
from plain.models import types


def generate_token() -> str:
    return binascii.hexlify(os.urandom(20)).decode()


@models.register_model
class APIKey(models.Model):
    uuid: UUID = types.UUIDField(default=uuid.uuid4)
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    updated_at: datetime = types.DateTimeField(auto_now=True)
    expires_at: datetime | None = types.DateTimeField(required=False, allow_null=True)
    last_used_at: datetime | None = types.DateTimeField(required=False, allow_null=True)

    name: str = types.CharField(max_length=255, required=False)

    token: str = types.CharField(max_length=40, default=generate_token)

    api_version: str = types.CharField(max_length=255, required=False)

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(
                fields=["uuid"], name="plainapi_apikey_unique_uuid"
            ),
            models.UniqueConstraint(
                fields=["token"], name="plainapi_apikey_unique_token"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name or str(self.uuid)
