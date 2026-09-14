"""Contract tests for Client ID Metadata Document clients (MCP SEP-991).

A client_id that is an HTTPS URL names a hosted metadata document. These
tests drive the full flow through the HTTP endpoints with the document fetch
stubbed at the network seam, using Claude's real documents as the fixtures.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from oauth_helpers import generate_pkce_pair
from plain.oauthserver import cimd
from plain.oauthserver.cimd import ClientMetadataError
from plain.oauthserver.models import OAuthApplication
from plain.test import Client
from plain.utils import timezone

CLAUDE_URL = "https://claude.ai/oauth/mcp-oauth-client-metadata"
CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
CLAUDE_DOCUMENT = {
    "client_id": CLAUDE_URL,
    "client_name": "Claude",
    "client_uri": "https://claude.ai",
    "redirect_uris": [CLAUDE_REDIRECT],
    "grant_types": [
        "authorization_code",
        "refresh_token",
        "urn:ietf:params:oauth:grant-type:jwt-bearer",
    ],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}

CLAUDE_CODE_URL = "https://claude.ai/oauth/claude-code-client-metadata"
CLAUDE_CODE_DOCUMENT = {
    "client_id": CLAUDE_CODE_URL,
    "client_name": "Claude Code",
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}


class FakeFetch:
    """Stands in for the network fetch: serves documents by URL and counts calls."""

    def __init__(self, documents: dict[str, dict], *, ttl: int = 3600):
        self.documents = documents
        self.ttl = ttl
        self.calls: list[str] = []
        self.failure: ClientMetadataError | None = None

    def __call__(self, url: str) -> tuple[dict, int]:
        self.calls.append(url)
        if self.failure is not None:
            raise self.failure
        if url not in self.documents:
            raise ClientMetadataError("Metadata document responded with status 404")
        return self.documents[url], self.ttl


@pytest.fixture
def fetch(monkeypatch):
    fake = FakeFetch(
        {CLAUDE_URL: CLAUDE_DOCUMENT, CLAUDE_CODE_URL: CLAUDE_CODE_DOCUMENT}
    )
    monkeypatch.setattr(cimd, "fetch_metadata_document", fake)
    return fake


def _authorize_params(client_id, redirect_uri, challenge, **extra):
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "offline_access",
        "state": "s",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **extra,
    }


class TestMetadata:
    def test_advertised_by_default(self, db):
        data = Client().get("/.well-known/oauth-authorization-server").json()
        # Claude requires both of these before it will use CIMD.
        assert data["client_id_metadata_document_supported"] is True
        assert "none" in data["token_endpoint_auth_methods_supported"]

    def test_omitted_when_disabled(self, db, monkeypatch):
        from plain.runtime import settings

        monkeypatch.setattr(
            settings, "OAUTH_SERVER_ALLOW_CLIENT_ID_METADATA_DOCUMENTS", False
        )
        data = Client().get("/.well-known/oauth-authorization-server").json()
        assert "client_id_metadata_document_supported" not in data


class TestEndToEnd:
    def test_claude_full_flow_without_registration(
        self, db, authenticated_client, user, fetch
    ):
        verifier, challenge = generate_pkce_pair()

        consent = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(CLAUDE_URL, CLAUDE_REDIRECT, challenge),
        )
        assert consent.status_code == 200
        body = consent.content.decode()
        assert "Claude" in body
        assert "Client hosted at <strong>claude.ai</strong>" in body
        assert "sent back to <strong>claude.ai</strong>" in body
        assert "runs on your own computer" not in body
        assert fetch.calls == [CLAUDE_URL]

        approve = authenticated_client.post(
            "/oauth/authorize",
            data=_authorize_params(
                CLAUDE_URL,
                CLAUDE_REDIRECT,
                challenge,
                action="approve",
                resource="https://mcp.example.com/mcp",
            ),
        )
        assert approve.status_code == 302
        assert approve.headers["Location"].startswith(CLAUDE_REDIRECT + "?")
        code = approve.headers["Location"].split("code=")[1].split("&")[0]
        # The stored document is fresh, so the POST didn't refetch.
        assert fetch.calls == [CLAUDE_URL]

        tokens = Client().post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CLAUDE_REDIRECT,
                "client_id": CLAUDE_URL,
                "code_verifier": verifier,
            },
        )
        assert tokens.status_code == 200
        access_token = tokens.json()["access_token"]
        refresh_token = tokens.json()["refresh_token"]

        from plain.oauthserver import validate_access_token

        stored = validate_access_token(
            access_token, resource="https://mcp.example.com/mcp"
        )
        assert stored is not None
        assert stored.user.id == user.id
        assert stored.application.client_id == CLAUDE_URL

        refreshed = Client().post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLAUDE_URL,
            },
        )
        assert refreshed.status_code == 200

        revoke = Client().post(
            "/oauth/revoke",
            data={"token": refreshed.json()["access_token"], "client_id": CLAUDE_URL},
        )
        assert revoke.status_code == 200

        # One row for the client, and the token endpoints never fetched.
        assert OAuthApplication.query.filter(client_id=CLAUDE_URL).count() == 1
        assert fetch.calls == [CLAUDE_URL]

    def test_claude_code_loopback_with_ephemeral_port(
        self, db, authenticated_client, fetch
    ):
        _, challenge = generate_pkce_pair()
        redirect_uri = "http://localhost:3118/callback"

        consent = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(CLAUDE_CODE_URL, redirect_uri, challenge),
        )
        assert consent.status_code == 200
        body = consent.content.decode()
        assert "Claude Code" in body
        assert "runs on your own computer" in body

        approve = authenticated_client.post(
            "/oauth/authorize",
            data=_authorize_params(
                CLAUDE_CODE_URL, redirect_uri, challenge, action="approve"
            ),
        )
        assert approve.status_code == 302
        assert approve.headers["Location"].startswith(redirect_uri + "?code=")

    def test_second_client_reuses_stored_document(
        self, db, authenticated_client, fetch
    ):
        _, challenge = generate_pkce_pair()
        for _ in range(3):
            response = authenticated_client.get(
                "/oauth/authorize",
                data=_authorize_params(CLAUDE_URL, CLAUDE_REDIRECT, challenge),
            )
            assert response.status_code == 200
        assert fetch.calls == [CLAUDE_URL]
        assert OAuthApplication.query.filter(client_id=CLAUDE_URL).count() == 1


class TestRefresh:
    def _stored(self, *, fetched_ago: timedelta, expired: bool = True):
        now = timezone.now()
        return OAuthApplication.query.create(
            client_id=CLAUDE_URL,
            name="Claude",
            redirect_uris=CLAUDE_REDIRECT,
            metadata_fetched_at=now - fetched_ago,
            metadata_expires_at=now - timedelta(seconds=1)
            if expired
            else now + timedelta(hours=1),
        )

    def test_expired_document_is_refetched_and_changes_applied(
        self, db, authenticated_client, fetch
    ):
        self._stored(fetched_ago=timedelta(hours=2))
        fetch.documents[CLAUDE_URL] = {
            **CLAUDE_DOCUMENT,
            "client_name": "Claude (renamed)",
            "redirect_uris": [
                CLAUDE_REDIRECT,
                "https://claude.ai/api/mcp/auth_callback2",
            ],
        }
        _, challenge = generate_pkce_pair()

        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(
                CLAUDE_URL, "https://claude.ai/api/mcp/auth_callback2", challenge
            ),
        )
        assert response.status_code == 200
        assert "Claude (renamed)" in response.content.decode()
        assert fetch.calls == [CLAUDE_URL]

        application = OAuthApplication.query.get(client_id=CLAUDE_URL)
        assert application.metadata_expires_at is not None
        assert application.metadata_expires_at > timezone.now()
        assert len(application.get_redirect_uris()) == 2

    def test_failed_refetch_serves_the_stored_document(
        self, db, authenticated_client, fetch
    ):
        self._stored(fetched_ago=timedelta(days=2))
        fetch.failure = ClientMetadataError(
            "Metadata document responded with status 503"
        )
        _, challenge = generate_pkce_pair()

        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(CLAUDE_URL, CLAUDE_REDIRECT, challenge),
        )
        assert response.status_code == 200
        assert "Claude" in response.content.decode()
        assert "Could not use client_id" not in response.content.decode()

    def test_stale_beyond_grace_period_fails(self, db, authenticated_client, fetch):
        self._stored(fetched_ago=timedelta(days=8))
        fetch.failure = ClientMetadataError(
            "Metadata document responded with status 503"
        )
        _, challenge = generate_pkce_pair()

        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(CLAUDE_URL, CLAUDE_REDIRECT, challenge),
        )
        body = response.content.decode()
        assert "Could not use client_id" in body
        assert "status 503" in body
        assert "code_challenge" not in body  # no consent form rendered


class TestRejections:
    def test_unfetchable_document_is_shown_not_redirected(
        self, db, authenticated_client, fetch
    ):
        unknown = "https://claude.ai/oauth/does-not-exist"
        _, challenge = generate_pkce_pair()

        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(unknown, CLAUDE_REDIRECT, challenge),
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "Could not use client_id https://claude.ai/oauth/does-not-exist" in body
        assert "status 404" in body
        assert not OAuthApplication.query.filter(client_id=unknown).exists()

    def test_redirect_uri_not_in_document(self, db, authenticated_client, fetch):
        _, challenge = generate_pkce_pair()
        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(
                CLAUDE_URL, "https://evil.example.com/cb", challenge
            ),
        )
        assert "Invalid redirect_uri" in response.content.decode()

    def test_invalid_url_never_fetched(self, db, authenticated_client, fetch):
        _, challenge = generate_pkce_pair()
        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(
                "https://claude.ai/oauth/../metadata", CLAUDE_REDIRECT, challenge
            ),
        )
        assert "dot segments" in response.content.decode()
        assert fetch.calls == []

    def test_token_endpoint_never_fetches(self, db, fetch):
        response = Client().post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "x",
                "redirect_uri": CLAUDE_REDIRECT,
                "client_id": CLAUDE_URL,
                "code_verifier": "y",
            },
        )
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_client"
        assert fetch.calls == []

    def test_disabled_setting_treats_url_as_unknown(
        self, db, authenticated_client, fetch, monkeypatch
    ):
        from plain.runtime import settings

        monkeypatch.setattr(
            settings, "OAUTH_SERVER_ALLOW_CLIENT_ID_METADATA_DOCUMENTS", False
        )
        _, challenge = generate_pkce_pair()
        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(CLAUDE_URL, CLAUDE_REDIRECT, challenge),
        )
        assert "Unknown client_id" in response.content.decode()
        assert fetch.calls == []

    def test_allowed_hosts(self, db, authenticated_client, fetch, monkeypatch):
        from plain.runtime import settings

        monkeypatch.setattr(
            settings, "OAUTH_SERVER_CLIENT_ID_METADATA_ALLOWED_HOSTS", ["example.com"]
        )
        _, challenge = generate_pkce_pair()
        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(CLAUDE_URL, CLAUDE_REDIRECT, challenge),
        )
        assert (
            "claude.ai is not an allowed client metadata host"
            in response.content.decode()
        )
        assert fetch.calls == []

        monkeypatch.setattr(
            settings, "OAUTH_SERVER_CLIENT_ID_METADATA_ALLOWED_HOSTS", ["claude.ai"]
        )
        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(CLAUDE_URL, CLAUDE_REDIRECT, challenge),
        )
        assert response.status_code == 200
        assert fetch.calls == [CLAUDE_URL]


class TestRegisteredClientsUnaffected:
    def test_random_client_id_still_looked_up(
        self, db, authenticated_client, public_app, fetch
    ):
        _, challenge = generate_pkce_pair()
        response = authenticated_client.get(
            "/oauth/authorize",
            data=_authorize_params(
                public_app.client_id, "http://localhost:3000/callback", challenge
            ),
        )
        assert response.status_code == 200
        body = response.content.decode()
        assert "Test App" in body
        assert "Client hosted at" not in body
        assert fetch.calls == []
