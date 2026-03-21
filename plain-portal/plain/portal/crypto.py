"""E2E encryption for portal sessions using SPAKE2 + NaCl.

Both sides derive a shared secret from the human-readable portal code
via SPAKE2 (a password-authenticated key exchange). An eavesdropper
observing the relay traffic cannot brute-force the code offline.

All messages after the key exchange are encrypted with NaCl SecretBox
(XSalsa20-Poly1305).

The portal code is never sent to the relay. Instead, a SHA-256 hash
of the code is used as the channel ID for pairing. The raw code is
only used locally for the SPAKE2 exchange.
"""

from __future__ import annotations

import base64
import hashlib
import json

import nacl.secret
import nacl.utils
import spake2


def channel_id(code: str) -> str:
    """Derive a relay channel ID from the portal code.

    Uses SHA-256 so the relay never learns the raw code and cannot
    perform SPAKE2 to impersonate either side.
    """
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


async def perform_key_exchange(ws, code: str, *, side: str) -> PortalEncryptor:
    """Run the SPAKE2 handshake over a WebSocket and return an encryptor.

    `side` must be "start" (SPAKE2_A / initiator) or "connect" (SPAKE2_B / joiner).
    """
    spake_cls = spake2.SPAKE2_A if side == "start" else spake2.SPAKE2_B
    spake_instance = spake_cls(code.encode("utf-8"))
    spake_msg = spake_instance.msg()

    await ws.send(base64.b64encode(spake_msg).decode("ascii"))
    peer_msg = base64.b64decode(await ws.recv())
    key = spake_instance.finish(peer_msg)
    return PortalEncryptor(key)


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
