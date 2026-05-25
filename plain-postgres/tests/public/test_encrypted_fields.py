from __future__ import annotations

import pytest
from app.examples.models.encrypted import SecretStore

from plain.postgres.fields.encrypted import (
    _ENCRYPTED_PREFIX,
    _decrypt,
    _encrypt,
    _get_fernet,
)


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
        with pytest.raises(ValueError, match="Could not decrypt"):
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
    def test_create_and_read(self, db):
        obj = SecretStore.query.create(name="test", api_key="sk-abc123")
        obj.refresh_from_db()
        assert obj.api_key == "sk-abc123"

    def test_update(self, db):
        obj = SecretStore.query.create(name="test", api_key="sk-old")
        obj.api_key = "sk-new"
        obj.save()
        obj.refresh_from_db()
        assert obj.api_key == "sk-new"

    def test_null_not_encrypted(self, db):
        """NULL values should stay as NULL, not get encrypted."""
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=None)
        obj.refresh_from_db()
        assert obj.config is None

    def test_queryset_values(self, db):
        """Raw DB values should be encrypted ciphertext."""
        SecretStore.query.create(name="test", api_key="sk-secret")
        raw = SecretStore.query.values_list("api_key", flat=True).first()
        # The raw value from values_list goes through from_db_value,
        # so it should be decrypted
        assert raw == "sk-secret"

    def test_long_text(self, db):
        long_text = "x" * 10000
        obj = SecretStore.query.create(name="test", api_key="sk-test", notes=long_text)
        obj.refresh_from_db()
        assert obj.notes == long_text

    def test_empty_string(self, db):
        obj = SecretStore.query.create(name="test", api_key="sk-test", notes="")
        obj.refresh_from_db()
        assert obj.notes == ""


class TestEncryptedJSONField:
    def test_dict(self, db):
        data = {"token": "abc", "scopes": ["read", "write"]}
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_list(self, db):
        data = [1, 2, "three"]
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_nested(self, db):
        data = {"oauth": {"access_token": "gho_xxx", "refresh_token": "ghr_yyy"}}
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=data)
        obj.refresh_from_db()
        assert obj.config == data

    def test_null(self, db):
        obj = SecretStore.query.create(name="test", api_key="sk-test", config=None)
        obj.refresh_from_db()
        assert obj.config is None


class TestLookupBlocking:
    def test_isnull_lookup_works(self, db):
        SecretStore.query.create(name="test", api_key="sk-test", config=None)
        assert SecretStore.query.filter(config__isnull=True).count() == 1

    def test_exact_lookup_allowed(self, db):
        """Exact is allowed so filter(field=None) works (ORM rewrites to isnull)."""
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_lookup("exact") is not None

    def test_filter_none_works(self, db):
        """filter(field=None) must work — ORM rewrites exact+None to isnull."""
        SecretStore.query.create(name="test", api_key="sk-test", config=None)
        assert SecretStore.query.filter(config=None).count() == 1

    def test_contains_lookup_blocked(self, db):
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_lookup("contains") is None

    def test_transform_blocked(self, db):
        field = SecretStore._model_meta.get_field("api_key")
        assert field.get_transform("lower") is None  # ty: ignore[unresolved-attribute]


class TestTypedQueryMethodsBlocked:
    """Encrypted fields must not expose typed-query comparison methods.

    The class-level overrides accept `Never`, so type checkers reject any
    call site. The runtime also raises TypeError as a safety net for callers
    that bypass type checking (e.g. dynamic code).
    """

    def test_equals_raises(self):
        with pytest.raises(TypeError, match=r"api_key.*does not support \.equals\("):
            SecretStore.api_key.equals("anything")  # ty: ignore[invalid-argument-type]

    def test_not_equal_raises(self):
        with pytest.raises(TypeError, match=r"does not support \.not_equal\("):
            SecretStore.api_key.not_equal("x")  # ty: ignore[invalid-argument-type]

    @pytest.mark.parametrize("method", ["gt", "gte", "lt", "lte"])
    def test_ordering_comparison_raises(self, method):
        with pytest.raises(TypeError, match=rf"does not support \.{method}\("):
            getattr(SecretStore.api_key, method)("x")

    def test_is_null_returns_correct_lookup(self):
        """is_null is the one comparison that makes sense on ciphertext."""
        from plain.postgres.query_utils import Q

        q = SecretStore.api_key.is_null()
        assert isinstance(q, Q)
        assert q.children == [("api_key__isnull", True)]

        q_false = SecretStore.api_key.is_null(False)
        assert q_false.children == [("api_key__isnull", False)]


class TestKwargFilterBlocked:
    """Block the legacy kwarg/Q path the same way the typed methods are
    blocked: `filter(api_key='x')` on an encrypted field would silently
    return zero rows because ciphertext is non-deterministic.
    `filter(api_key=None)` is preserved so it still rewrites to IS NULL.
    """

    def test_filter_non_none_raises(self, db):
        with pytest.raises(
            TypeError,
            match=r"api_key.*cannot be filtered by equality against a non-None value",
        ):
            SecretStore.query.filter(api_key="sk-test").count()

    def test_exclude_non_none_raises(self, db):
        with pytest.raises(
            TypeError,
            match=r"api_key.*cannot be filtered by equality against a non-None value",
        ):
            SecretStore.query.exclude(api_key="sk-test").count()

    def test_filter_none_still_rewrites_to_isnull(self, db):
        """filter(field=None) must continue to work — ORM rewrites to isnull."""
        SecretStore.query.create(name="test", api_key="sk-test", config=None)
        assert SecretStore.query.filter(config=None).count() == 1


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
