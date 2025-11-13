from __future__ import annotations

import binascii
import os
from uuid import uuid4

from plain.models import (
    CharField,
    DateTimeField,
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
    uuid = UUIDField(default=uuid4, allow_null=True)
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    expires_at = DateTimeField(required=False, allow_null=True)
    last_used_at = DateTimeField(required=False, allow_null=True)

    name = CharField(max_length=255, required=False)

    token = CharField(max_length=40, default=generate_token)

    api_version = CharField(max_length=255, required=False)

    model_options = Options(
        constraints=[
            UniqueConstraint(fields=["uuid"], name="plainapi_apikey_unique_uuid"),
            UniqueConstraint(fields=["token"], name="plainapi_apikey_unique_token"),
        ],
    )

    def __str__(self) -> str:
        return self.name or str(self.uuid)
