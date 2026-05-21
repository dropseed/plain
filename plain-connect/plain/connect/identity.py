from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_BYTES = 12

# Domain separator — the verifier (a Cloudflare Worker, not Python) must
# prepend the exact same tag before HMAC. Lets the same secret sign other
# message kinds later without confusion. If you change this string, update
# the Worker side in lockstep.
_RENDER_TOKEN_TAG = "render-token:"


def _derive_key(secret: str) -> bytes:
    # Plain SHA-256 (no salt/HKDF) because `secret` is a high-entropy
    # server-generated value, not a user password.
    return hashlib.sha256(secret.encode()).digest()


def encrypt_identity(user_id: int | str, secret: str) -> str:
    """AES-256-GCM-encrypt a user id. Returns base64url(nonce + ciphertext + tag)."""
    key = _derive_key(secret)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, str(user_id).encode(), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def sign_render_token(secret: str, *, now: int | None = None) -> str:
    """Sign a fresh render timestamp. Returns `<unix_seconds>.<hex_hmac_sha256>`, or `""` when no secret."""
    if not secret:
        return ""
    ts = int(now if now is not None else time.time())
    message = (_RENDER_TOKEN_TAG + str(ts)).encode()
    mac = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"{ts}.{mac}"
