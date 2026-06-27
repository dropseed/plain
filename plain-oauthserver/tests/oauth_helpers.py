"""Shared test helpers.

A uniquely-named module (rather than `conftest`) so type-checking resolves it
unambiguously across the workspace's shared test path.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any

from plain.utils import timezone


def generate_pkce_pair() -> tuple[str, str]:
    """Return a (code_verifier, code_challenge) S256 pair."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def issue_token_pair(
    application: Any,
    user: Any,
    *,
    access: str = "access-value",
    refresh: str = "refresh-value",
    scope: str = "read",
    resource: str = "",
) -> tuple[Any, Any]:
    """Persist a paired access + refresh token with known plaintext values."""
    from plain.oauthserver.models import AccessToken, RefreshToken, _hash_token

    now = timezone.now()
    access_token = AccessToken.query.create(
        application=application,
        user=user,
        scope=scope,
        resource=resource,
        token_hash=_hash_token(access),
        expires_at=now + timedelta(hours=1),
    )
    refresh_token = RefreshToken.query.create(
        application=application,
        user=user,
        access_token=access_token,
        token_hash=_hash_token(refresh),
        expires_at=now + timedelta(days=30),
    )
    return access_token, refresh_token
