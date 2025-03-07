import binascii
import os
import uuid

from plain import models


def generate_token():
    return binascii.hexlify(os.urandom(20)).decode()


@models.register_model
class APIKey(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(required=False, allow_null=True)
    last_used_at = models.DateTimeField(required=False, allow_null=True)

    name = models.CharField(max_length=255, required=False)

    token = models.CharField(max_length=40, default=generate_token, unique=True)

    # Connect to a user, for example, from your own model:
    # api_key = models.OneToOneField(
    #     APIKey,
    #     on_delete=models.CASCADE,
    #     related_name="user",
    #     allow_null=True,
    #     required=False,
    # )

    def __str__(self):
        return self.name or str(self.uuid)
