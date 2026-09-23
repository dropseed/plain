"""The encrypt/decrypt primitives under `plain.postgres.fields.encrypted`.

Below the contract: `_encrypt`/`_decrypt`/`_get_fernet` are private, and the
user-visible behavior they support (values round-trip, old keys keep working
through SECRET_KEY_FALLBACKS) is asserted through the model in
`tests/public/test_encrypted_fields.py`. These pin the mechanism.
"""

import pytest
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
