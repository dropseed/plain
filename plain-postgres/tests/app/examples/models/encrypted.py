from __future__ import annotations

from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class SecretStore(postgres.Model):
    """Model for testing encrypted fields."""

    name: Field[str] = types.TextField(max_length=100)
    api_key: Field[str] = types.EncryptedTextField(max_length=200)
    notes: Field[str] = types.EncryptedTextField(required=False, default="")
    # EncryptedJSONField can't express a column DEFAULT (Fernet ciphertext is
    # non-deterministic), so there's no `default=` to make it omittable -- it
    # stays a required constructor argument.
    config: Field[dict | None] = types.EncryptedJSONField(
        required=False, allow_null=True
    )
