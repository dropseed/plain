from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class SecretStore(postgres.Model):
    """Model for testing encrypted fields."""

    name: str = types.TextField(max_length=100)
    api_key: str = types.EncryptedTextField(max_length=200)
    notes: str = types.EncryptedTextField(required=False)
    config: dict = types.EncryptedJSONField(required=False, allow_null=True)

    query: postgres.QuerySet[SecretStore] = postgres.QuerySet()
