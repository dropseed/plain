from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class SecretStore(postgres.Model):
    """Model for testing encrypted fields."""

    name = types.TextField(max_length=100)
    api_key = types.EncryptedTextField(max_length=200)
    notes = types.EncryptedTextField(required=False)
    config = types.EncryptedJSONField(required=False, allow_null=True)

    query: postgres.QuerySet[SecretStore] = postgres.QuerySet()
