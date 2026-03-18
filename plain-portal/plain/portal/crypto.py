"""E2E encryption for portal sessions using SPAKE2 + NaCl.

Both sides derive a shared secret from the human-readable portal code
via SPAKE2 (a password-authenticated key exchange). An eavesdropper
observing the relay traffic cannot brute-force the code offline.

All messages after the key exchange are encrypted with NaCl SecretBox
(XSalsa20-Poly1305).
"""

from __future__ import annotations

import json

import nacl.secret
import nacl.utils
import spake2


def create_spake2_initiator(code: str) -> spake2.SPAKE2_A:
    """Create the SPAKE2 side A (remote/start side)."""
    return spake2.SPAKE2_A(code.encode("utf-8"))


def create_spake2_joiner(code: str) -> spake2.SPAKE2_B:
    """Create the SPAKE2 side B (local/connect side)."""
    return spake2.SPAKE2_B(code.encode("utf-8"))


class PortalEncryptor:
    """Encrypts and decrypts portal messages using a shared key."""

    def __init__(self, key: bytes) -> None:
        # SPAKE2 produces a 32-byte key, which is exactly what SecretBox wants.
        self._box = nacl.secret.SecretBox(key)

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data. Returns nonce + ciphertext."""
        return self._box.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data. Expects nonce + ciphertext."""
        return self._box.decrypt(data)

    def encrypt_message(self, msg: dict) -> bytes:
        """Encrypt a JSON-serializable message dict."""
        plaintext = json.dumps(msg).encode("utf-8")
        return self.encrypt(plaintext)

    def decrypt_message(self, data: bytes) -> dict:
        """Decrypt and parse a JSON message dict."""
        plaintext = self.decrypt(data)
        return json.loads(plaintext.decode("utf-8"))
