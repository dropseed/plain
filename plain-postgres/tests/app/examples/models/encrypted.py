from plain.postgres import EncryptedField, Field, types

from plain import postgres


@postgres.register_model
class SecretStore(postgres.Model):
    """Model for testing encrypted fields."""

    name: Field[str] = types.TextField(max_length=100)
    api_key: EncryptedField[str] = types.EncryptedTextField(max_length=200)
    notes: EncryptedField[str] = types.EncryptedTextField(required=False, default="")
    config: EncryptedField[dict | None] = types.EncryptedJSONField(
        required=False, allow_null=True, default=None
    )
