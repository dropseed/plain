from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12


def _derive_key(identity_key: str) -> bytes:
    """Derive a 32-byte AES-256 key from the endpoint's identity_key.

    A plain SHA-256 is sufficient (no salt/HKDF) because identity_key is a
    high-entropy server-generated secret, not a user password. The beacon
    Worker's decrypt must derive the key identically.
    """
    return hashlib.sha256(identity_key.encode()).digest()


def encrypt_identity(user_id: int | str, identity_key: str) -> str:
    """Encrypt a user id into an opaque token for the pageview beacon.

    AES-256-GCM with a random nonce. The beacon endpoint decrypts it with the
    same identity_key, so the raw user id never appears in page HTML. Returns
    base64url(nonce + ciphertext + GCM tag).
    """
    key = _derive_key(identity_key)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, str(user_id).encode(), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()
