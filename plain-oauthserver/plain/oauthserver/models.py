from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlparse, urlunparse

from plain import postgres
from plain.postgres import types
from plain.utils import timezone

__all__ = [
    "OAuthApplication",
    "AuthorizationCode",
    "AccessToken",
    "RefreshToken",
]

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _generate_token() -> str:
    """A new opaque bearer token, handed to the client once and never stored."""
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    """What we persist for access/refresh tokens — a DB leak can't be replayed."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _normalize_redirect_uri(uri: str) -> str:
    """Drop the port from loopback URIs so they match regardless of it (RFC 8252)."""
    parsed = urlparse(uri)
    if parsed.scheme == "http" and parsed.hostname in _LOOPBACK_HOSTS:
        return urlunparse(parsed._replace(netloc=parsed.hostname or ""))
    return uri


@postgres.register_model
class OAuthApplication(postgres.Model):
    """A registered OAuth client (Claude's connector, a CLI).

    Always a public client — proven by PKCE on the code exchange and by the
    refresh token on refresh, never a client secret.
    """

    client_id = types.RandomStringField(length=32)
    name = types.TextField(max_length=255, default="", required=False)
    redirect_uris = types.TextField(max_length=2000)
    created_at = types.DateTimeField(create_now=True)

    query: postgres.QuerySet[OAuthApplication] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["client_id"],
                name="plainoauthserver_oauthapplication_unique_client_id",
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name

    def get_redirect_uris(self) -> list[str]:
        return self.redirect_uris.split()

    def is_valid_redirect_uri(self, uri: str) -> bool:
        normalized = _normalize_redirect_uri(uri)
        return any(
            _normalize_redirect_uri(registered) == normalized
            for registered in self.get_redirect_uris()
        )


@postgres.register_model
class AuthorizationCode(postgres.Model):
    """Short-lived, single-use code from the authorization endpoint.

    Stored in plaintext: it's ephemeral, single-use, and bound by PKCE.
    """

    code = types.RandomStringField(length=48)
    application = types.ForeignKeyField(OAuthApplication, on_delete=postgres.CASCADE)
    user = types.ForeignKeyField("users.User", on_delete=postgres.CASCADE)
    redirect_uri = types.TextField(max_length=2000)
    scope = types.TextField(max_length=500, default="", required=False)
    resource = types.TextField(max_length=2000, default="", required=False)
    code_challenge = types.TextField(max_length=128)
    created_at = types.DateTimeField(create_now=True)
    expires_at = types.DateTimeField()
    used = types.BooleanField(default=False)

    query: postgres.QuerySet[AuthorizationCode] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            # The code is the credential redeemed at the token endpoint, so
            # uniqueness is enforced by the DB rather than left to chance.
            postgres.UniqueConstraint(
                fields=["code"],
                name="plainoauthserver_authorizationcode_unique_code",
            ),
        ],
        indexes=[
            postgres.Index(
                name="plainoauthserver_authorizationcode_application_id_idx",
                fields=["application"],
            ),
            postgres.Index(
                name="plainoauthserver_authorizationcode_user_id_idx",
                fields=["user"],
            ),
        ],
    )

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def verify_code_challenge(self, code_verifier: str) -> bool:
        """Verify a PKCE code_verifier against the stored S256 challenge."""
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return secrets.compare_digest(computed, self.code_challenge)


@postgres.register_model
class AccessToken(postgres.Model):
    """A bearer access token. Only its hash is stored."""

    token_hash = types.TextField(max_length=64)
    application = types.ForeignKeyField(OAuthApplication, on_delete=postgres.CASCADE)
    user = types.ForeignKeyField("users.User", on_delete=postgres.CASCADE)
    scope = types.TextField(max_length=500, default="", required=False)
    resource = types.TextField(max_length=2000, default="", required=False)
    created_at = types.DateTimeField(create_now=True)
    expires_at = types.DateTimeField()
    revoked = types.BooleanField(default=False)

    query: postgres.QuerySet[AccessToken] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["token_hash"],
                name="plainoauthserver_accesstoken_unique_token_hash",
            ),
        ],
        indexes=[
            postgres.Index(
                name="plainoauthserver_accesstoken_user_id_idx", fields=["user"]
            ),
            postgres.Index(
                name="plainoauthserver_accesstoken_application_id_idx",
                fields=["application"],
            ),
        ],
    )

    def is_valid(self) -> bool:
        return not self.revoked and timezone.now() < self.expires_at

    @property
    def scopes(self) -> frozenset[str]:
        """The granted scope as a set — the shape a resource server checks against."""
        return frozenset(self.scope.split())


@postgres.register_model
class RefreshToken(postgres.Model):
    """A refresh token. Only its hash is stored; rotated on every use.

    Scope and resource live on the linked `access_token` — a refresh always
    has one (non-null CASCADE FK), so there's nothing to duplicate here.
    """

    token_hash = types.TextField(max_length=64)
    application = types.ForeignKeyField(OAuthApplication, on_delete=postgres.CASCADE)
    user = types.ForeignKeyField("users.User", on_delete=postgres.CASCADE)
    # CASCADE is load-bearing for the cleanup chore: it deletes access tokens
    # only when no live refresh token still points at them (see chores.py).
    access_token = types.ForeignKeyField(AccessToken, on_delete=postgres.CASCADE)
    created_at = types.DateTimeField(create_now=True)
    expires_at = types.DateTimeField()
    revoked = types.BooleanField(default=False)

    query: postgres.QuerySet[RefreshToken] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["token_hash"],
                name="plainoauthserver_refreshtoken_unique_token_hash",
            ),
        ],
        indexes=[
            postgres.Index(
                name="plainoauthserver_refreshtoken_application_id_idx",
                fields=["application"],
            ),
            postgres.Index(
                name="plainoauthserver_refreshtoken_user_id_idx", fields=["user"]
            ),
            postgres.Index(
                name="plainoauthserver_refreshtoken_access_token_id_idx",
                fields=["access_token"],
            ),
        ],
    )

    def is_valid(self) -> bool:
        return not self.revoked and timezone.now() < self.expires_at
