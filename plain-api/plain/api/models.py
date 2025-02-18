import binascii
import os
import uuid

from plain import models


def generate_token():
    return binascii.hexlify(os.urandom(20)).decode()


@models.register_model
class APIKey(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    last_used_at = models.DateTimeField(blank=True, null=True)

    name = models.CharField(max_length=255, blank=True)

    token = models.CharField(max_length=40, default=generate_token, unique=True)

    # Connect to a user, for example, from your own model:
    # api_key = models.OneToOneField(
    #     APIKey,
    #     on_delete=models.CASCADE,
    #     related_name="user",
    #     null=True,
    #     blank=True,
    # )

    def __str__(self):
        return self.name or str(self.uuid)
