from __future__ import annotations

import binascii
import os
from datetime import datetime
from uuid import UUID, uuid4

from plain.models import (
    CharField,
    DateTimeField,
    Field,
    Model,
    Options,
    UniqueConstraint,
    UUIDField,
    register_model,
)


def generate_token() -> str:
    return binascii.hexlify(os.urandom(20)).decode()


@register_model
class APIKey(Model):
    uuid: Field[UUID | None, UUIDField(default=uuid4)] = None
    created_at: Field[datetime | None, DateTimeField(auto_now_add=True)] = None
    updated_at: Field[datetime | None, DateTimeField(auto_now=True)] = None
    expires_at: Field[datetime | None, DateTimeField(allow_null=True)] = None
    last_used_at: Field[datetime | None, DateTimeField(allow_null=True)] = None

    name: Field[str, CharField(max_length=255)] = ""

    token: Field[str, CharField(max_length=40, default=generate_token)]

    api_version: Field[str, CharField(max_length=255)] = ""

    model_options = Options(
        constraints=[
            UniqueConstraint(fields=["uuid"], name="plainapi_apikey_unique_uuid"),
            UniqueConstraint(fields=["token"], name="plainapi_apikey_unique_token"),
        ],
    )

    def __str__(self) -> str:
        return self.name or str(self.uuid)
