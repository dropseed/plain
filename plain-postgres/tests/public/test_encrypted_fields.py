from __future__ import annotations

from app.examples.models.encrypted import SecretStore
from plain.postgres.exceptions import FieldError
from plain.postgres.fields.encrypted import (
    _ENCRYPTED_PREFIX,
    _decrypt,
    _encrypt,
    _get_fernet,
)
from plain.test import raises


class TestEncryptDecryptFunctions:
    """Test the low-level encrypt/decrypt functions."""

    def test_encrypt_returns_prefixed_string(self):
        result = _encrypt("hello")
        assert result.startswith(_ENCRYPTED_PREFIX)

    def test_decrypt_reverses_encrypt(self):
        encrypted = _encrypt("secret value")
        assert _decrypt(encrypted) == "secret value"

    def test_encrypt_is_nondeterministic(self):
        """Same plaintext should produce different ciphertext each time."""
        a = _encrypt("same input")
        b = _encrypt("same input")
        assert a != b

    def test_decrypt_plaintext_passthrough(self):
        """Unencrypted values pass through for migration support."""
        assert _decrypt("just a plain string") == "just a plain string"

    def test_decrypt_invalid_token_raises(self):
        """Corrupted encrypted data should raise a clear error."""
        with raises(ValueError, match="Could not decrypt"):
            _decrypt(_ENCRYPTED_PREFIX + "not-valid-fernet-data")

    def test_encrypt_empty_string(self):
        encrypted = _encrypt("")
        assert _decrypt(encrypted) == ""

    def test_encrypt_unicode(self):
        encrypted = _encrypt("hello \U0001f30d unicode")
        assert _decrypt(encrypted) == "hello \U0001f30d unicode"

    def test_fernet_is_cached(self):
        """MultiFernet instance should be cached for same key."""
        from plain.runtime import settings

        key = settings.SECRET_KEY
        fallbacks = tuple(settings.SECRET_KEY_FALLBACKS)
        f1 = _get_fernet(key, fallbacks)
        f2 = _get_fernet(key, fallbacks)
        assert f1 is f2


class TestEncryptedTextField:
    def test_create_and_read(self):
        obj = SecretStore.query.create(name="test", api_key="sk-abc123")
        obj.refresh_from_db()
        assert obj.api_key == "sk-abc123"

    def test_update(self):
        obj = SecretStore.query.create(name="test", api_key="sk-old")
        obj.api_key = "sk-new"
        obj.update()
        obj.refresh_from_db()
        assert obj.api_key == "sk-new"

    def test_null_not_encrypted(self):
        """NULL values should stay as NULL, not get encrypted."""
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=None)
        obj.refresh_from_db()
        assert obj.config is None

    def test_queryset_values(self):
        """Raw DB values should be encrypted ciphertext."""
        SecretStore.query.create(name="test", api_key="sk-secret")
        raw = SecretStore.query.values_list("api_key", flat=True).first()
        # The raw value from values_list goes through from_db_value,
        # so it should be decrypted
        assert raw == "sk-secret"

    def test_long_text(self):
        long_text = "x" * 10000
        obj = SecretStore.query.create(name="test", api_key="sk-test", notes=long_text)
        obj.refresh_from_db()
        assert obj.notes == long_text

    def test_empty_string(self):
        obj = SecretStore.query.create(name="test", api_key="sk-test", notes="")
        obj.refresh_from_db()
        assert obj.notes == ""


class TestEncryptedJSONField:
    def test_dict(self):
        data = {"token": "abc", "scopes": ["read", "write"]}
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_list(self):
        data = [1, 2, "three"]
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_nested(self):
        data = {"oauth": {"access_token": "gho_xxx", "refresh_token": "ghr_yyy"}}
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_null(self):
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=None)
        obj.refresh_from_db()
        assert obj.config is None


class TestLookupBlocking:
    def test_isnull_lookup_works(self):
        SecretStore.query.create(name="test", api_key="sk-test", config=None)
        assert SecretStore.query.filter(config__isnull=True).count() == 1

    def test_exact_lookup_allowed(self):
        """Exact is allowed so filter(field=None) works (ORM rewrites to isnull)."""
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_lookup("exact") is not None

    def test_filter_none_works(self):
        """filter(field=None) must work — ORM rewrites exact+None to isnull."""
        SecretStore.query.create(name="test", api_key="sk-test", config=None)
        assert SecretStore.query.filter(config=None).count() == 1

    def test_contains_lookup_blocked(self):
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_lookup("contains") is None

    def test_transform_blocked(self):
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_transform("lower") is None  # ty: ignore[unresolved-attribute]

    def test_unsupported_lookup_raises_field_error(self):
        """An unsupported lookup on an encrypted field must fail as a normal
        FieldError at query-build time — not leak into transform resolution
        (which once raised a bare TypeError via class-level get_lookups)."""
        with raises(FieldError):
            SecretStore.query.filter(api_key__contains="x")
        with raises(FieldError):
            SecretStore.query.filter(config__has_key="token")


class TestKeyRotation:
    def test_decrypt_with_fallback_key(self):
        """Data encrypted with an old key should decrypt when that key is in fallbacks."""
        old_key = "old-secret-key-for-testing"
        new_key = "new-secret-key-for-testing"

        # Encrypt with old key
        old_fernet = _get_fernet(old_key, ())
        token = old_fernet.encrypt(b"sensitive data")
        encrypted_value = _ENCRYPTED_PREFIX + token.decode("ascii")

        # Decrypt with new key + old key as fallback
        new_fernet = _get_fernet(new_key, (old_key,))
        raw_token = encrypted_value[len(_ENCRYPTED_PREFIX) :]
        result = new_fernet.decrypt(raw_token.encode("ascii")).decode("utf-8")
        assert result == "sensitive data"

    def test_different_keys_produce_different_fernet(self):
        f1 = _get_fernet("key-a", ())
        f2 = _get_fernet("key-b", ())
        assert f1 is not f2


class TestEncryptedJSONFieldDefault:
    """`EncryptedJSONField` has no *persistent* default — ciphertext is
    non-deterministic, so no literal column DEFAULT can be expressed. It still
    accepts `default=None` on a nullable field, the same None-only affordance
    the ColumnField-direct fields (UUIDField, DateTimeField, ForeignKeyField)
    use to mark a field optional in the typed constructor."""

    def test_default_none_is_accepted_on_a_nullable_field(self):
        from plain.postgres.fields.encrypted import EncryptedJSONField

        field = EncryptedJSONField(required=False, allow_null=True, default=None)

        assert field.get_default() is None
        # Nothing is stored, so no DB DEFAULT and no migration churn.
        assert not field.has_persistent_literal_default()
        assert not field.has_persistent_column_default()

    def test_default_none_makes_the_field_omittable(self, db):
        """The point of the `default=None`: `config` is declared with it on
        SecretStore, so it can be left out of the constructor entirely and the
        row still saves. The type checker agrees (`./scripts/type-check`)."""
        obj = SecretStore(name="test", api_key="sk-omitted")
        assert obj.config is None

        obj.create()
        assert SecretStore.query.get(name="test").config is None

    def test_default_none_requires_allow_null(self):
        from plain.postgres.fields.encrypted import EncryptedJSONField

        with pytest.raises(TypeError, match="requires allow_null=True"):
            EncryptedJSONField(required=False, default=None)

    @pytest.mark.parametrize("value", [{}, {"a": 1}, [], "", 0])
    def test_literal_default_is_still_rejected(self, value):
        """Any non-None default would need ciphertext, which is
        non-deterministic — there is no literal to put in the column."""
        from plain.postgres.fields.encrypted import EncryptedJSONField

        with pytest.raises(TypeError, match="does not accept a persistent default"):
            EncryptedJSONField(required=False, allow_null=True, default=value)
