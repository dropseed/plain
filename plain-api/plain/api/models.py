from __future__ import annotations

import binascii
import os
import secrets
import uuid
from datetime import datetime
from uuid import UUID

from plain import models
from plain.models import types
from plain.utils import timezone

__all__ = ["APIKey", "DeviceGrant"]


def generate_token() -> str:
    return binascii.hexlify(os.urandom(20)).decode()


def generate_device_code() -> str:
    return binascii.hexlify(os.urandom(32)).decode()


# Consonants only (excluding ambiguous chars) to avoid forming words
_USER_CODE_CHARS = "BCDFGHJKLMNPQRSTVWXZ"


def generate_user_code() -> str:
    code = "".join(secrets.choice(_USER_CODE_CHARS) for _ in range(8))
    return code[:4] + "-" + code[4:]


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

    query: models.QuerySet[APIKey] = models.QuerySet()

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


@models.register_model
class DeviceGrant(models.Model):
    """
    Stores a pending device authorization grant (RFC 8628).

    The device requests a code pair, displays the user_code to the user,
    and polls with the device_code until the user approves or the grant expires.
    """

    created_at: datetime = types.DateTimeField(auto_now_add=True)

    device_code: str = types.CharField(max_length=64, default=generate_device_code)
    user_code: str = types.CharField(max_length=9, default=generate_user_code)

    status: str = types.CharField(max_length=20, default="pending")
    scope: str = types.CharField(max_length=500, required=False)
    expires_at: datetime = types.DateTimeField()
    interval: int = types.IntegerField(default=5)

    # Set when the user approves and the device claims the token
    api_key = types.ForeignKeyField(
        APIKey,
        on_delete=models.SET_NULL,
        allow_null=True,
        required=False,
    )

    query: models.QuerySet[DeviceGrant] = models.QuerySet()

    model_options = models.Options(
        constraints=[
            models.UniqueConstraint(
                fields=["device_code"],
                name="plainapi_devicegrant_unique_device_code",
            ),
            models.UniqueConstraint(
                fields=["user_code"],
                condition=models.Q(status="pending"),
                name="plainapi_devicegrant_unique_pending_user_code",
            ),
        ],
    )

    STATUS_PENDING = "pending"
    STATUS_AUTHORIZED = "authorized"
    STATUS_DENIED = "denied"

    def __str__(self) -> str:
        return f"{self.user_code} ({self.status})"

    def is_expired(self) -> bool:
        return self.expires_at < timezone.now()

    def authorize(self, *, api_key: APIKey) -> None:
        """Mark the grant as authorized with the given API key."""
        self.status = self.STATUS_AUTHORIZED
        self.api_key = api_key
        self.save(update_fields=["status", "api_key_id"])

    def deny(self) -> None:
        """Mark the grant as denied."""
        self.status = self.STATUS_DENIED
        self.save(update_fields=["status"])

    @classmethod
    def cleanup_expired(cls) -> int:
        """Delete expired grants. Returns the number of deleted grants."""
        count, _ = cls.query.filter(expires_at__lt=timezone.now()).delete()
        return count
