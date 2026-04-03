from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime

from plain import postgres
from plain.postgres import types
from plain.runtime import SettingsReference


def generate_client_id() -> str:
    """Generate a random client ID (32 hex chars)."""
    return secrets.token_hex(16)


def generate_client_secret() -> str:
    """Generate a random client secret (64 hex chars)."""
    return secrets.token_hex(32)


def generate_token() -> str:
    """Generate a random token (40 hex chars)."""
    return secrets.token_hex(20)


def generate_code() -> str:
    """Generate a random authorization code (32 hex chars)."""
    return secrets.token_hex(16)


@postgres.register_model
class OAuthApplication(postgres.Model):
    """A registered OAuth client application."""

    client_id: str = types.TextField(max_length=64, default=generate_client_id)
    client_secret: str = types.TextField(max_length=128, default=generate_client_secret)
    name: str = types.TextField(max_length=255)
    redirect_uris: str = types.TextField(
        max_length=2000,
    )
    created_at: datetime = types.DateTimeField(auto_now_add=True)

    query: postgres.QuerySet[OAuthApplication] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["client_id"],
                name="plainoauthprovider_application_unique_client_id",
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name

    def get_redirect_uris(self) -> list[str]:
        return self.redirect_uris.split()

    def is_valid_redirect_uri(self, uri: str) -> bool:
        return uri in self.get_redirect_uris()

    def verify_client_secret(self, secret: str) -> bool:
        return secrets.compare_digest(self.client_secret, secret)


@postgres.register_model
class AuthorizationCode(postgres.Model):
    """Short-lived authorization code for the authorization code flow."""

    code: str = types.TextField(max_length=64, default=generate_code)
    application = types.ForeignKeyField(
        OAuthApplication,
        on_delete=postgres.CASCADE,
    )
    user = types.ForeignKeyField(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=postgres.CASCADE,
    )
    redirect_uri: str = types.TextField(max_length=2000)
    scope: str = types.TextField(max_length=500, required=False)
    code_challenge: str = types.TextField(max_length=128)
    code_challenge_method: str = types.TextField(max_length=10)
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    expires_at: datetime = types.DateTimeField()
    used: bool = types.BooleanField(default=False)

    query: postgres.QuerySet[AuthorizationCode] = postgres.QuerySet()

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                name="plainoauthprovider_authcode_code_idx",
                fields=["code"],
            ),
            postgres.Index(
                name="plainoauthprovider_authcode_application_id_idx",
                fields=["application"],
            ),
        ],
    )

    def is_expired(self) -> bool:
        from plain.utils import timezone

        return timezone.now() >= self.expires_at

    def verify_code_challenge(self, code_verifier: str) -> bool:
        """Verify a PKCE code_verifier against the stored code_challenge."""
        if self.code_challenge_method != "S256":
            return False

        # S256: BASE64URL(SHA256(code_verifier)) == code_challenge
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return secrets.compare_digest(computed, self.code_challenge)


@postgres.register_model
class AccessToken(postgres.Model):
    """An OAuth access token."""

    token: str = types.TextField(max_length=64, default=generate_token)
    application = types.ForeignKeyField(
        OAuthApplication,
        on_delete=postgres.CASCADE,
    )
    user = types.ForeignKeyField(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=postgres.CASCADE,
    )
    scope: str = types.TextField(max_length=500, required=False)
    created_at: datetime = types.DateTimeField(auto_now_add=True)
    expires_at: datetime = types.DateTimeField()
    revoked: bool = types.BooleanField(default=False)

    query: postgres.QuerySet[AccessToken] = postgres.QuerySet()

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                name="plainoauthprovider_accesstoken_token_idx",
                fields=["token"],
            ),
            postgres.Index(
                name="plainoauthprovider_accesstoken_application_id_idx",
                fields=["application"],
            ),
            postgres.Index(
                name="plainoauthprovider_accesstoken_user_id_idx",
                fields=["user"],
            ),
        ],
    )

    def is_valid(self) -> bool:
        from plain.utils import timezone

        return not self.revoked and timezone.now() < self.expires_at


@postgres.register_model
class RefreshToken(postgres.Model):
    """An OAuth refresh token for token rotation."""

    token: str = types.TextField(max_length=64, default=generate_token)
    application = types.ForeignKeyField(
        OAuthApplication,
        on_delete=postgres.CASCADE,
    )
    user = types.ForeignKeyField(
        SettingsReference("AUTH_USER_MODEL"),
        on_delete=postgres.CASCADE,
    )
    access_token = types.ForeignKeyField(
        AccessToken,
        on_delete=postgres.CASCADE,
    )
    revoked: bool = types.BooleanField(default=False)

    query: postgres.QuerySet[RefreshToken] = postgres.QuerySet()

    model_options = postgres.Options(
        indexes=[
            postgres.Index(
                name="plainoauthprovider_refreshtoken_token_idx",
                fields=["token"],
            ),
            postgres.Index(
                name="plainoauthprovider_refreshtoken_access_token_id_idx",
                fields=["access_token"],
            ),
        ],
    )

    def is_valid(self) -> bool:
        return not self.revoked
