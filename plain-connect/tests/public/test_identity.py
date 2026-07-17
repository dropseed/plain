import base64
import hashlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from plain.connect.identity import encrypt_identity
from plain.test import raises

IDENTITY_KEY = "endpoint-identity-secret"


def _decrypt(token: str, identity_key: str) -> str:
    """Independent inverse of encrypt_identity — proves the wire format.

    The beacon Worker decrypts identically; this mirrors that logic rather
    than reusing the encrypt-side code, so a format change can't pass silently.
    """
    key = hashlib.sha256(identity_key.encode()).digest()
    raw = base64.urlsafe_b64decode(token)
    nonce, ciphertext = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode()


def test_encrypt_identity_round_trips():
    token = encrypt_identity(42, IDENTITY_KEY)
    assert _decrypt(token, IDENTITY_KEY) == "42"


def test_encrypt_identity_accepts_string_user_id():
    token = encrypt_identity("user-abc", IDENTITY_KEY)
    assert _decrypt(token, IDENTITY_KEY) == "user-abc"


def test_encrypt_identity_uses_a_random_nonce():
    # Same input twice must not produce the same token — otherwise the
    # ciphertext would leak which page loads belong to the same user.
    assert encrypt_identity(1, IDENTITY_KEY) != encrypt_identity(1, IDENTITY_KEY)


def test_encrypt_identity_token_is_url_safe():
    token = encrypt_identity(1, IDENTITY_KEY)
    # Safe to drop straight into an HTML attribute / URL with no escaping.
    assert token == base64.urlsafe_b64encode(base64.urlsafe_b64decode(token)).decode()


def test_wrong_key_cannot_decrypt():
    token = encrypt_identity(7, IDENTITY_KEY)
    with raises(InvalidTag):
        _decrypt(token, "the-wrong-key")
