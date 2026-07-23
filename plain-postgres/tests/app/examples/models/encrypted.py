from __future__ import annotations

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class SecretStore(postgres.Model):
    """Model for testing encrypted fields."""

    name: Field[str] = types.TextField(max_length=100)
    api_key: Field[str] = types.EncryptedTextField(max_length=200)
    notes: Field[str] = types.EncryptedTextField(required=False)
    config: Field[dict | None] = types.EncryptedJSONField(
        required=False, allow_null=True, default=None
    )
