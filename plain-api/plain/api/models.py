import binascii
import os
import uuid

from plain import models


def generate_token():
    return binascii.hexlify(os.urandom(20)).decode()


@models.register_model
class APIKey(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(required=False, allow_null=True)
    last_used_at = models.DateTimeField(required=False, allow_null=True)

    name = models.CharField(max_length=255, required=False)

    token = models.CharField(max_length=40, default=generate_token)

    api_version = models.CharField(max_length=255, required=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["uuid"], name="plainapi_apikey_unique_uuid"
            ),
            models.UniqueConstraint(
                fields=["token"], name="plainapi_apikey_unique_token"
            ),
        ]

    def __str__(self):
        return self.name or str(self.uuid)
