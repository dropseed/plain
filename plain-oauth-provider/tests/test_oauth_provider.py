"""OAuth 2.1 authorization server tests.

Tests cover:
- Authorization server metadata (RFC 8414)
- Authorization code flow with PKCE (RFC 7636)
- Token exchange and refresh (RFC 6749)
- Token revocation (RFC 7009)
- Error cases and edge cases
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta

import pytest
from app.users.models import User

from plain.oauth_provider.models import (
    AccessToken,
    AuthorizationCode,
    OAuthApplication,
    RefreshToken,
)
from plain.test import Client
from plain.utils import timezone

# -- PKCE helpers --


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_hex(32)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# -- Fixtures --


@pytest.fixture
def user(db):
    return User.query.create(email="test@example.com")


@pytest.fixture
def oauth_app(db):
    return OAuthApplication.query.create(
        name="Test App",
        redirect_uris="http://localhost:3000/callback http://localhost:3000/other",
    )


@pytest.fixture
def authenticated_client(user):
    client = Client()
    client.force_login(user)
    return client


# -- Authorization Server Metadata (RFC 8414) --


class TestMetadata:
    def test_metadata_endpoint(self, db):
        client = Client()
        response = client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200

        data = response.json()
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "revocation_endpoint" in data
        assert data["response_types_supported"] == ["code"]
        assert "authorization_code" in data["grant_types_supported"]
        assert "refresh_token" in data["grant_types_supported"]
        assert data["code_challenge_methods_supported"] == ["S256"]


# -- Authorization Endpoint --


class TestAuthorize:
    def test_requires_login(self, db, oauth_app):
        client = Client()
        code_verifier, code_challenge = generate_pkce_pair()
        response = client.get(
            "/oauth/authorize/",
            data={
                "response_type": "code",
                "client_id": oauth_app.client_id,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        # Should redirect to login
        assert response.status_code == 302

    def test_consent_page_renders(self, authenticated_client, oauth_app):
        code_verifier, code_challenge = generate_pkce_pair()
        response = authenticated_client.get(
            "/oauth/authorize/",
            data={
                "response_type": "code",
                "client_id": oauth_app.client_id,
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "Test App" in body
        assert "Approve" in body
        assert "Deny" in body

    def test_missing_pkce_shows_error(self, authenticated_client, oauth_app):
        response = authenticated_client.get(
            "/oauth/authorize/",
            data={
                "response_type": "code",
                "client_id": oauth_app.client_id,
                "redirect_uri": "http://localhost:3000/callback",
            },
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "code_challenge" in body

    def test_invalid_client_shows_error(self, authenticated_client):
        code_verifier, code_challenge = generate_pkce_pair()
        response = authenticated_client.get(
            "/oauth/authorize/",
            data={
                "response_type": "code",
                "client_id": "nonexistent",
                "redirect_uri": "http://localhost:3000/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "Unknown client_id" in body

    def test_approve_redirects_with_code(self, authenticated_client, oauth_app):
        code_verifier, code_challenge = generate_pkce_pair()
        response = authenticated_client.post(
            "/oauth/authorize/",
            data={
                "action": "approve",
                "response_type": "code",
                "client_id": oauth_app.client_id,
                "redirect_uri": "http://localhost:3000/callback",
                "scope": "read",
                "state": "xyz123",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 302
        location = response.headers["Location"]
        assert "http://localhost:3000/callback" in location
        assert "code=" in location
        assert "state=xyz123" in location

        # Verify code was created in DB
        assert AuthorizationCode.query.filter(application=oauth_app).exists()

    def test_deny_redirects_with_error(self, authenticated_client, oauth_app):
        code_verifier, code_challenge = generate_pkce_pair()
        response = authenticated_client.post(
            "/oauth/authorize/",
            data={
                "action": "deny",
                "response_type": "code",
                "client_id": oauth_app.client_id,
                "redirect_uri": "http://localhost:3000/callback",
                "state": "xyz123",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 302
        location = response.headers["Location"]
        assert "error=access_denied" in location
        assert "state=xyz123" in location


# -- Token Endpoint --


class TestToken:
    def _create_auth_code(
        self,
        oauth_app,
        user,
        code_challenge,
        redirect_uri="http://localhost:3000/callback",
    ):
        return AuthorizationCode.query.create(
            application=oauth_app,
            user=user,
            redirect_uri=redirect_uri,
            scope="read",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=timezone.now() + timedelta(minutes=10),
        )

    def test_exchange_code_for_tokens(self, db, user, oauth_app):
        """Full PKCE authorization code exchange."""
        code_verifier, code_challenge = generate_pkce_pair()
        auth_code = self._create_auth_code(oauth_app, user, code_challenge)

        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": "http://localhost:3000/callback",
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] > 0
        assert data["scope"] == "read"

        # Verify no-store header per RFC
        assert "no-store" in response.headers.get("Cache-Control", "")

    def test_pkce_verification_fails_with_wrong_verifier(self, db, user, oauth_app):
        code_verifier, code_challenge = generate_pkce_pair()
        auth_code = self._create_auth_code(oauth_app, user, code_challenge)

        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": "http://localhost:3000/callback",
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "code_verifier": "wrong_verifier_value",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"
        assert "PKCE" in response.json()["error_description"]

    def test_code_single_use(self, db, user, oauth_app):
        """Authorization codes are single-use per RFC."""
        code_verifier, code_challenge = generate_pkce_pair()
        auth_code = self._create_auth_code(oauth_app, user, code_challenge)

        client = Client()
        data = {
            "grant_type": "authorization_code",
            "code": auth_code.code,
            "redirect_uri": "http://localhost:3000/callback",
            "client_id": oauth_app.client_id,
            "client_secret": oauth_app.client_secret,
            "code_verifier": code_verifier,
        }

        # First exchange succeeds
        response = client.post("/oauth/token/", data=data)
        assert response.status_code == 200

        # Second exchange fails
        response = client.post("/oauth/token/", data=data)
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_expired_code_rejected(self, db, user, oauth_app):
        code_verifier, code_challenge = generate_pkce_pair()
        auth_code = AuthorizationCode.query.create(
            application=oauth_app,
            user=user,
            redirect_uri="http://localhost:3000/callback",
            scope="",
            code_challenge=code_challenge,
            code_challenge_method="S256",
            expires_at=timezone.now() - timedelta(minutes=1),  # Already expired
        )

        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": "http://localhost:3000/callback",
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_redirect_uri_must_match(self, db, user, oauth_app):
        code_verifier, code_challenge = generate_pkce_pair()
        auth_code = self._create_auth_code(oauth_app, user, code_challenge)

        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": "http://evil.com/callback",  # Wrong URI
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"

    def test_invalid_client_secret_rejected(self, db, user, oauth_app):
        code_verifier, code_challenge = generate_pkce_pair()
        auth_code = self._create_auth_code(oauth_app, user, code_challenge)

        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": "http://localhost:3000/callback",
                "client_id": oauth_app.client_id,
                "client_secret": "wrong_secret",
                "code_verifier": code_verifier,
            },
        )
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_client"

    def test_missing_code_verifier_rejected(self, db, user, oauth_app):
        """PKCE is mandatory — missing code_verifier must fail."""
        code_verifier, code_challenge = generate_pkce_pair()
        auth_code = self._create_auth_code(oauth_app, user, code_challenge)

        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": "http://localhost:3000/callback",
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                # No code_verifier
            },
        )
        assert response.status_code == 400
        assert "code_verifier" in response.json()["error_description"]

    def test_unsupported_grant_type(self, db, oauth_app):
        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "implicit",
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "unsupported_grant_type"


# -- Refresh Token --


class TestRefreshToken:
    def _issue_tokens(self, oauth_app, user):
        """Create an access+refresh token pair directly."""
        access = AccessToken.query.create(
            application=oauth_app,
            user=user,
            scope="read",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        refresh = RefreshToken.query.create(
            application=oauth_app,
            user=user,
            access_token=access,
        )
        return access, refresh

    def test_refresh_token_exchange(self, db, user, oauth_app):
        old_access, old_refresh = self._issue_tokens(oauth_app, user)

        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "refresh_token",
                "refresh_token": old_refresh.token,
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # New tokens should be different from old ones
        assert data["access_token"] != old_access.token
        assert data["refresh_token"] != old_refresh.token

        # Old tokens should be revoked (token rotation)
        old_access.refresh_from_db()
        old_refresh.refresh_from_db()
        assert old_access.revoked is True
        assert old_refresh.revoked is True

    def test_revoked_refresh_token_rejected(self, db, user, oauth_app):
        _, old_refresh = self._issue_tokens(oauth_app, user)
        old_refresh.revoked = True
        old_refresh.save(update_fields=["revoked"])

        client = Client()
        response = client.post(
            "/oauth/token/",
            data={
                "grant_type": "refresh_token",
                "refresh_token": old_refresh.token,
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"


# -- Token Revocation (RFC 7009) --


class TestRevocation:
    def test_revoke_access_token(self, db, user, oauth_app):
        access = AccessToken.query.create(
            application=oauth_app,
            user=user,
            scope="",
            expires_at=timezone.now() + timedelta(hours=1),
        )

        client = Client()
        response = client.post(
            "/oauth/revoke/",
            data={
                "token": access.token,
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 200

        access.refresh_from_db()
        assert access.revoked is True

    def test_revoke_refresh_token(self, db, user, oauth_app):
        access = AccessToken.query.create(
            application=oauth_app,
            user=user,
            scope="",
            expires_at=timezone.now() + timedelta(hours=1),
        )
        refresh = RefreshToken.query.create(
            application=oauth_app,
            user=user,
            access_token=access,
        )

        client = Client()
        response = client.post(
            "/oauth/revoke/",
            data={
                "token": refresh.token,
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 200

        refresh.refresh_from_db()
        assert refresh.revoked is True
        # Associated access token should also be revoked
        access.refresh_from_db()
        assert access.revoked is True

    def test_revoke_unknown_token_returns_200(self, db, oauth_app):
        """RFC 7009: server responds 200 even for unknown tokens."""
        client = Client()
        response = client.post(
            "/oauth/revoke/",
            data={
                "token": "nonexistent_token",
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 200

    def test_revoke_without_token_returns_200(self, db, oauth_app):
        """RFC 7009: server responds 200 even if token param is missing."""
        client = Client()
        response = client.post(
            "/oauth/revoke/",
            data={
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 200


# -- PKCE Verification Unit Tests --


class TestPKCE:
    def test_s256_verification(self, db, user, oauth_app):
        code_verifier, code_challenge = generate_pkce_pair()
        auth_code = AuthorizationCode(
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        assert auth_code.verify_code_challenge(code_verifier) is True

    def test_s256_wrong_verifier(self, db, user, oauth_app):
        _, code_challenge = generate_pkce_pair()
        auth_code = AuthorizationCode(
            code_challenge=code_challenge,
            code_challenge_method="S256",
        )
        assert auth_code.verify_code_challenge("wrong") is False

    def test_plain_method_rejected(self, db):
        """OAuth 2.1 requires S256, plain method is not supported."""
        auth_code = AuthorizationCode(
            code_challenge="some_challenge",
            code_challenge_method="plain",
        )
        assert auth_code.verify_code_challenge("some_challenge") is False


# -- Full End-to-End Flow --


class TestEndToEndFlow:
    def test_complete_authorization_code_flow(
        self, authenticated_client, oauth_app, user
    ):
        """Test the complete OAuth flow: authorize → token → use → refresh → revoke."""
        code_verifier, code_challenge = generate_pkce_pair()

        # Step 1: User approves authorization
        response = authenticated_client.post(
            "/oauth/authorize/",
            data={
                "action": "approve",
                "response_type": "code",
                "client_id": oauth_app.client_id,
                "redirect_uri": "http://localhost:3000/callback",
                "scope": "read write",
                "state": "test_state",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 302
        location = response.headers["Location"]
        # Extract code from redirect URL
        code = location.split("code=")[1].split("&")[0]

        # Step 2: Exchange code for tokens
        token_client = Client()
        response = token_client.post(
            "/oauth/token/",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://localhost:3000/callback",
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
                "code_verifier": code_verifier,
            },
        )
        assert response.status_code == 200
        tokens = response.json()
        access_token = tokens["access_token"]
        refresh_token_value = tokens["refresh_token"]

        # Verify access token is valid in DB
        at = AccessToken.query.get(token=access_token)
        assert at.is_valid()
        assert at.user.id == user.id

        # Step 3: Refresh the token
        response = token_client.post(
            "/oauth/token/",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token_value,
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 200
        new_tokens = response.json()
        new_access_token = new_tokens["access_token"]

        # Old access token should be revoked
        at.refresh_from_db()
        assert at.revoked is True

        # New access token should be valid
        new_at = AccessToken.query.get(token=new_access_token)
        assert new_at.is_valid()

        # Step 4: Revoke the new token
        response = token_client.post(
            "/oauth/revoke/",
            data={
                "token": new_access_token,
                "client_id": oauth_app.client_id,
                "client_secret": oauth_app.client_secret,
            },
        )
        assert response.status_code == 200
        new_at.refresh_from_db()
        assert new_at.revoked is True
