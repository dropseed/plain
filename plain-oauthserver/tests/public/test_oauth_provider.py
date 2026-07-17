"""Contract tests for the OAuth 2.1 authorization server endpoints."""

from __future__ import annotations

from datetime import timedelta

from oauth_helpers import (
    generate_pkce_pair,
    issue_token_pair,
    login_as,
    make_public_app,
    make_user,
)

from plain.oauthserver.models import (
    AccessToken,
    AuthorizationCode,
    OAuthApplication,
    RefreshToken,
)
from plain.test import Client, override_settings
from plain.utils import timezone

REDIRECT_URI = "http://localhost:3000/callback"


def _make_auth_code(application, user, code_challenge, *, redirect_uri=REDIRECT_URI):
    return AuthorizationCode.query.create(
        application=application,
        user=user,
        redirect_uri=redirect_uri,
        scope="read",
        code_challenge=code_challenge,
        expires_at=timezone.now() + timedelta(minutes=10),
    )


# -- Authorization server metadata (RFC 8414) --


class TestMetadata:
    def test_metadata_document(self):
        data = Client().get("/.well-known/oauth-authorization-server").json_data
        assert data["response_types_supported"] == ["code"]
        assert "authorization_code" in data["grant_types_supported"]
        assert "refresh_token" in data["grant_types_supported"]
        assert data["code_challenge_methods_supported"] == ["S256"]
        # Public clients + DCR are what Claude needs.
        assert "none" in data["token_endpoint_auth_methods_supported"]
        assert "registration_endpoint" in data
        assert "offline_access" in data["scopes_supported"]


# -- Dynamic client registration (RFC 7591) --


class TestRegister:
    def test_register_public_client(self):
        response = Client().post(
            "/oauth/register",
            json_data={
                "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
                "client_name": "Claude",
                "token_endpoint_auth_method": "none",
            },
        )
        assert response.status_code == 201
        data = response.json_data
        assert data["client_id"]
        assert "client_secret" not in data  # always a public client
        assert data["token_endpoint_auth_method"] == "none"
        assert OAuthApplication.query.filter(client_id=data["client_id"]).exists()

    def test_register_overrides_requested_auth_method_to_public(self):
        # We only issue public clients, so a request for a secret-based method
        # still yields a public client with no secret.
        response = Client().post(
            "/oauth/register",
            json_data={
                "redirect_uris": ["https://app.example.com/callback"],
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
        assert response.status_code == 201
        data = response.json_data
        assert data["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in data

    def test_register_rejects_missing_redirect_uris(self):
        response = Client().post(
            "/oauth/register",
            json_data={"client_name": "x"},
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "invalid_redirect_uri"

    def test_register_rejects_non_https_redirect(self):
        response = Client().post(
            "/oauth/register",
            json_data={"redirect_uris": ["http://evil.example.com/cb"]},
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "invalid_redirect_uri"

    def test_register_rejects_whitespace_smuggled_redirect(self):
        # A value with internal whitespace would split into a second, unvalidated
        # URI once stored space-joined.
        response = Client().post(
            "/oauth/register",
            json_data={
                "redirect_uris": [
                    "https://ok.example.com/cb http://evil.example.com/cb"
                ]
            },
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "invalid_redirect_uri"


class TestRegistrationDisabled:
    """OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION = False locks down DCR."""

    def test_register_returns_403(self):
        with override_settings(OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION=False):
            response = Client().post(
                "/oauth/register",
                json_data={"redirect_uris": ["https://app.example.com/cb"]},
            )
            assert response.status_code == 403

    def test_metadata_omits_registration_endpoint(self):
        with override_settings(OAUTH_SERVER_ALLOW_DYNAMIC_REGISTRATION=False):
            data = Client().get("/.well-known/oauth-authorization-server").json_data
            assert "registration_endpoint" not in data


# -- Authorization endpoint --


class TestAuthorize:
    def test_requires_login(self):
        public_app = make_public_app()
        _, challenge = generate_pkce_pair()
        response = Client().get(
            "/oauth/authorize",
            query_params={
                "response_type": "code",
                "client_id": public_app.client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 302

    def test_consent_page_renders(self):
        public_app = make_public_app()
        client = login_as(make_user())
        _, challenge = generate_pkce_pair()
        response = client.get(
            "/oauth/authorize",
            query_params={
                "response_type": "code",
                "client_id": public_app.client_id,
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "Test App" in body
        assert "Approve" in body
        assert "Deny" in body

    def test_missing_pkce_shows_error(self):
        public_app = make_public_app()
        client = login_as(make_user())
        response = client.get(
            "/oauth/authorize",
            query_params={
                "response_type": "code",
                "client_id": public_app.client_id,
                "redirect_uri": REDIRECT_URI,
            },
        )
        assert response.status_code == 200
        assert "code_challenge" in response.content.decode()

    def test_approve_redirects_with_code_and_iss(self):
        public_app = make_public_app()
        client = login_as(make_user())
        _, challenge = generate_pkce_pair()
        response = client.post(
            "/oauth/authorize",
            form_data={
                "action": "approve",
                "response_type": "code",
                "client_id": public_app.client_id,
                "redirect_uri": REDIRECT_URI,
                "scope": "read",
                "state": "xyz123",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 302
        location = response.headers["Location"]
        assert REDIRECT_URI in location
        assert "code=" in location
        assert "state=xyz123" in location
        assert "iss=" in location  # RFC 9207
        assert AuthorizationCode.query.filter(application=public_app).exists()

    def test_deny_redirects_with_error(self):
        public_app = make_public_app()
        client = login_as(make_user())
        _, challenge = generate_pkce_pair()
        response = client.post(
            "/oauth/authorize",
            form_data={
                "action": "deny",
                "response_type": "code",
                "client_id": public_app.client_id,
                "redirect_uri": REDIRECT_URI,
                "state": "xyz123",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 302
        assert "error=access_denied" in response.headers["Location"]
        assert "state=xyz123" in response.headers["Location"]  # state survives deny

    def test_rejects_unsupported_scope(self):
        public_app = make_public_app()
        client = login_as(make_user())
        _, challenge = generate_pkce_pair()
        response = client.post(
            "/oauth/authorize",
            form_data={
                "action": "approve",
                "response_type": "code",
                "client_id": public_app.client_id,
                "redirect_uri": REDIRECT_URI,
                "scope": "read admin",  # "admin" is not in OAUTH_SERVER_SCOPES_SUPPORTED
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 400
        assert not AuthorizationCode.query.filter(application=public_app).exists()

    def test_rejects_unregistered_redirect_uri(self):
        # The open-redirect / code-injection guard: an approve POST whose
        # redirect_uri isn't registered to the client must be refused outright,
        # never redirected to and never minting a code.
        public_app = make_public_app()
        client = login_as(make_user())
        _, challenge = generate_pkce_pair()
        response = client.post(
            "/oauth/authorize",
            form_data={
                "action": "approve",
                "response_type": "code",
                "client_id": public_app.client_id,
                "redirect_uri": "https://evil.example.com/cb",
                "scope": "read",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert response.status_code == 400
        assert "evil.example.com" not in response.headers.get("Location", "")
        assert not AuthorizationCode.query.filter(application=public_app).exists()


# -- Token endpoint --


class TestToken:
    def test_public_client_exchange_without_secret(self):
        user = make_user()
        public_app = make_public_app()
        verifier, challenge = generate_pkce_pair()
        auth_code = _make_auth_code(public_app, user, challenge)

        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": REDIRECT_URI,
                "client_id": public_app.client_id,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 200
        data = response.json_data
        assert data["token_type"] == "Bearer"
        assert data["access_token"]
        assert data["refresh_token"]
        assert "no-store" in response.headers.get("Cache-Control", "")
        # Stored hashed, not as the plaintext we returned.
        assert not AccessToken.query.filter(token_hash=data["access_token"]).exists()

    def test_unknown_client_rejected(self):
        user = make_user()
        public_app = make_public_app()
        verifier, challenge = generate_pkce_pair()
        auth_code = _make_auth_code(public_app, user, challenge)
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": REDIRECT_URI,
                "client_id": "does-not-exist",
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 401
        assert response.json_data["error"] == "invalid_client"

    def test_code_cannot_be_redeemed_by_another_client(self):
        # The code lookup is scoped by application, so a code stolen by a
        # different (valid) client is useless — guards against cross-client theft.
        user = make_user()
        public_app = make_public_app()
        thief = OAuthApplication.query.create(name="Thief", redirect_uris=REDIRECT_URI)
        verifier, challenge = generate_pkce_pair()
        auth_code = _make_auth_code(public_app, user, challenge)
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": REDIRECT_URI,
                "client_id": thief.client_id,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "invalid_grant"

    def test_pkce_failure(self):
        user = make_user()
        public_app = make_public_app()
        _, challenge = generate_pkce_pair()
        auth_code = _make_auth_code(public_app, user, challenge)
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": REDIRECT_URI,
                "client_id": public_app.client_id,
                "code_verifier": "wrong-verifier",
            },
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "invalid_grant"

    def test_code_is_single_use(self):
        user = make_user()
        public_app = make_public_app()
        verifier, challenge = generate_pkce_pair()
        auth_code = _make_auth_code(public_app, user, challenge)
        payload = {
            "grant_type": "authorization_code",
            "code": auth_code.code,
            "redirect_uri": REDIRECT_URI,
            "client_id": public_app.client_id,
            "code_verifier": verifier,
        }
        client = Client()
        assert client.post("/oauth/token", form_data=payload).status_code == 200
        assert client.post("/oauth/token", form_data=payload).status_code == 400

    def test_expired_code_rejected(self):
        user = make_user()
        public_app = make_public_app()
        verifier, challenge = generate_pkce_pair()
        auth_code = AuthorizationCode.query.create(
            application=public_app,
            user=user,
            redirect_uri=REDIRECT_URI,
            scope="",
            code_challenge=challenge,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": REDIRECT_URI,
                "client_id": public_app.client_id,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "invalid_grant"

    def test_redirect_uri_must_match(self):
        user = make_user()
        public_app = make_public_app()
        verifier, challenge = generate_pkce_pair()
        auth_code = _make_auth_code(public_app, user, challenge)
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": "http://localhost:3000/evil",
                "client_id": public_app.client_id,
                "code_verifier": verifier,
            },
        )
        assert response.status_code == 400

    def test_missing_verifier_rejected(self):
        user = make_user()
        public_app = make_public_app()
        _, challenge = generate_pkce_pair()
        auth_code = _make_auth_code(public_app, user, challenge)
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": auth_code.code,
                "redirect_uri": REDIRECT_URI,
                "client_id": public_app.client_id,
            },
        )
        assert response.status_code == 400
        assert "code_verifier" in response.json_data["error_description"]

    def test_unsupported_grant_type(self):
        public_app = make_public_app()
        response = Client().post(
            "/oauth/token",
            form_data={"grant_type": "implicit", "client_id": public_app.client_id},
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "unsupported_grant_type"


# -- Refresh token rotation --


class TestRefresh:
    def test_rotation(self):
        user = make_user()
        public_app = make_public_app()
        old_access, old_refresh = issue_token_pair(public_app, user)
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "refresh_token",
                "refresh_token": "refresh-value",
                "client_id": public_app.client_id,
            },
        )
        assert response.status_code == 200
        data = response.json_data
        assert data["access_token"] != "access-value"
        assert data["refresh_token"] != "refresh-value"

        old_access.refresh_from_db()
        old_refresh.refresh_from_db()
        assert old_access.revoked is True
        assert old_refresh.revoked is True

    def test_revoked_refresh_rejected(self):
        user = make_user()
        public_app = make_public_app()
        _, old_refresh = issue_token_pair(public_app, user)
        old_refresh.revoked = True
        old_refresh.update(fields=["revoked"])
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "refresh_token",
                "refresh_token": "refresh-value",
                "client_id": public_app.client_id,
            },
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "invalid_grant"

    def test_expired_refresh_rejected(self):
        user = make_user()
        public_app = make_public_app()
        _, old_refresh = issue_token_pair(public_app, user)
        old_refresh.expires_at = timezone.now() - timedelta(minutes=1)
        old_refresh.update(fields=["expires_at"])
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "refresh_token",
                "refresh_token": "refresh-value",
                "client_id": public_app.client_id,
            },
        )
        assert response.status_code == 400

    def test_refresh_token_is_single_use(self):
        # OAuth 2.1 rotation: re-presenting a refresh token after it rotated
        # away is rejected (the canonical replay property, as one sequence).
        user = make_user()
        public_app = make_public_app()
        issue_token_pair(public_app, user)
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": "refresh-value",
            "client_id": public_app.client_id,
        }
        client = Client()
        assert client.post("/oauth/token", form_data=payload).status_code == 200
        replay = client.post("/oauth/token", form_data=payload)
        assert replay.status_code == 400
        assert replay.json_data["error"] == "invalid_grant"

    def test_refresh_cannot_be_used_by_another_client(self):
        user = make_user()
        public_app = make_public_app()
        thief = OAuthApplication.query.create(name="Thief", redirect_uris=REDIRECT_URI)
        issue_token_pair(public_app, user)
        response = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "refresh_token",
                "refresh_token": "refresh-value",
                "client_id": thief.client_id,
            },
        )
        assert response.status_code == 400
        assert response.json_data["error"] == "invalid_grant"


# -- Revocation (RFC 7009) --


class TestRevocation:
    def test_revoke_access_token(self):
        user = make_user()
        public_app = make_public_app()
        access, _ = issue_token_pair(public_app, user)
        response = Client().post(
            "/oauth/revoke",
            form_data={"token": "access-value", "client_id": public_app.client_id},
        )
        assert response.status_code == 200
        access.refresh_from_db()
        assert access.revoked is True

    def test_revoke_refresh_cascades_to_access(self):
        user = make_user()
        public_app = make_public_app()
        access, refresh = issue_token_pair(public_app, user)
        response = Client().post(
            "/oauth/revoke",
            form_data={"token": "refresh-value", "client_id": public_app.client_id},
        )
        assert response.status_code == 200
        refresh.refresh_from_db()
        access.refresh_from_db()
        assert refresh.revoked is True
        assert access.revoked is True

    def test_revoke_unknown_token_is_200(self):
        public_app = make_public_app()
        response = Client().post(
            "/oauth/revoke",
            form_data={"token": "nope", "client_id": public_app.client_id},
        )
        assert response.status_code == 200


# -- Full end-to-end flow (DCR → authorize → token → refresh → revoke) --


class TestEndToEnd:
    def test_dcr_then_full_public_client_flow(self):
        user = make_user()
        client = login_as(user)
        register = Client().post(
            "/oauth/register",
            json_data={
                "redirect_uris": [REDIRECT_URI],
                "client_name": "Claude",
                "token_endpoint_auth_method": "none",
            },
        )
        client_id = register.json_data["client_id"]

        verifier, challenge = generate_pkce_pair()
        approve = client.post(
            "/oauth/authorize",
            form_data={
                "action": "approve",
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "scope": "read",
                "state": "s",
                "resource": "https://mcp.example.com/mcp",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        code = approve.headers["Location"].split("code=")[1].split("&")[0]

        tokens = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert tokens.status_code == 200
        access_token = tokens.json_data["access_token"]
        refresh_token = tokens.json_data["refresh_token"]

        # Token is audience-bound to the resource from the authorize request.
        from plain.oauthserver import validate_access_token

        stored = validate_access_token(
            access_token, resource="https://mcp.example.com/mcp"
        )
        assert stored is not None
        assert stored.user.id == user.id

        refreshed = Client().post(
            "/oauth/token",
            form_data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
        )
        assert refreshed.status_code == 200

        revoke = Client().post(
            "/oauth/revoke",
            form_data={
                "token": refreshed.json_data["access_token"],
                "client_id": client_id,
            },
        )
        assert revoke.status_code == 200
        assert RefreshToken.query.filter(application__client_id=client_id).count() == 2
