"""Tests for validate_access_token — the resource-server side."""

from __future__ import annotations

from datetime import timedelta

from oauth_helpers import (
    generate_pkce_pair,
    issue_token_pair,
    make_public_app,
    make_user,
)

from plain.oauthserver import validate_access_token
from plain.oauthserver.models import AuthorizationCode
from plain.test import Client
from plain.utils import timezone

REDIRECT_URI = "http://localhost:3000/callback"
RESOURCE = "https://mcp.example.com/mcp"


class TestValidateAccessToken:
    def test_valid_token(self):
        user = make_user()
        public_app = make_public_app()
        access, _ = issue_token_pair(public_app, user, access="tok")
        result = validate_access_token("tok")
        assert result is not None
        assert result.id == access.id
        assert result.user.id == user.id

    def test_unknown_token(self):
        assert validate_access_token("does-not-exist") is None

    def test_revoked_token(self):
        user = make_user()
        public_app = make_public_app()
        access, _ = issue_token_pair(public_app, user, access="tok")
        access.revoked = True
        access.update(fields=["revoked"])
        assert validate_access_token("tok") is None

    def test_expired_token(self):
        user = make_user()
        public_app = make_public_app()
        access, _ = issue_token_pair(public_app, user, access="tok")
        access.expires_at = timezone.now() - timedelta(minutes=1)
        access.update(fields=["expires_at"])
        assert validate_access_token("tok") is None

    def test_audience_match(self):
        user = make_user()
        public_app = make_public_app()
        issue_token_pair(public_app, user, access="tok", resource=RESOURCE)
        assert validate_access_token("tok", resource=RESOURCE) is not None

    def test_audience_mismatch_rejected(self):
        user = make_user()
        public_app = make_public_app()
        issue_token_pair(public_app, user, access="tok", resource=RESOURCE)
        assert validate_access_token("tok", resource="https://other/mcp") is None

    def test_unbound_token_is_audience_agnostic(self):
        # A token minted with no resource (empty) validates at any endpoint —
        # audience binding is opt-in, set by passing `resource` at issue time.
        user = make_user()
        public_app = make_public_app()
        issue_token_pair(public_app, user, access="tok")  # resource defaults to ""
        assert validate_access_token("tok", resource="https://anything/mcp") is not None

    def test_roundtrip_from_token_endpoint(self):
        """Issue through the real flow, then validate the returned bearer —
        proves the hash-at-rest roundtrip (plaintext out, hash stored)."""
        user = make_user()
        public_app = make_public_app()
        verifier, challenge = generate_pkce_pair()
        code = AuthorizationCode.query.create(
            application=public_app,
            user=user,
            redirect_uri=REDIRECT_URI,
            scope="read",
            resource=RESOURCE,
            code_challenge=challenge,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": code.code,
                "redirect_uri": REDIRECT_URI,
                "client_id": public_app.client_id,
                "code_verifier": verifier,
            },
        )
        access_token = response.json_data["access_token"]

        validated = validate_access_token(access_token, resource=RESOURCE)
        assert validated is not None
        assert validated.user.id == user.id
        assert validated.resource == RESOURCE
