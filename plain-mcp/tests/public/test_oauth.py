"""OAuth resource-server tests: the 401 challenge, bearer auth, and RFC 9728
protected-resource metadata that let an MCP client discover the auth server.

Requests go through the shared `mcp_post` fixture (tests/conftest.py), which
builds the `_meta` envelope and mirrored headers every request must carry.
"""

from __future__ import annotations

import json

from plain.mcp.views import PROTOCOL_VERSION
from plain.test import Client


class TestChallenge:
    def test_missing_token_returns_401_with_www_authenticate(self, mcp_post) -> None:
        response = mcp_post("/oauth-mcp", "server/discover")
        assert response.status_code == 401
        challenge = response.headers["WWW-Authenticate"]
        assert challenge.startswith("Bearer ")
        # Points at this endpoint's protected-resource metadata (RFC 9728).
        assert (
            'resource_metadata="https://testserver/.well-known/'
            'oauth-protected-resource/oauth-mcp"' in challenge
        )

    def test_invalid_token_returns_401_with_challenge(self, mcp_post) -> None:
        client = Client(headers={"Authorization": "Bearer nope"})
        response = mcp_post("/oauth-mcp", "server/discover", client=client)
        assert response.status_code == 401
        # RFC 6750: a supplied-but-rejected token is flagged invalid_token.
        assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]

    def test_valid_token_authenticates(self, mcp_post) -> None:
        client = Client(headers={"Authorization": "Bearer valid-token"})
        response = mcp_post("/oauth-mcp", "server/discover", client=client)
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["supportedVersions"] == [PROTOCOL_VERSION]

    def test_lowercase_bearer_scheme_accepted(self, mcp_post) -> None:
        # RFC 7235: the auth-scheme is matched case-insensitively.
        client = Client(headers={"Authorization": "bearer valid-token"})
        response = mcp_post("/oauth-mcp", "server/discover", client=client)
        assert response.status_code == 200

    def test_authenticated_tool_call_sees_user_and_scopes(self, mcp_post) -> None:
        # The headline contract: a tool reads self.mcp.user / .scopes end to end.
        client = Client(headers={"Authorization": "Bearer valid-token"})
        response = mcp_post(
            "/oauth-mcp",
            "tools/call",
            {"name": "WhoAmI", "arguments": {}},
            client=client,
        )
        assert response.status_code == 200
        body = response.json()
        result = json.loads(body["result"]["content"][0]["text"])
        assert result == {"user": "alice", "scopes": ["read"]}


class TestProtectedResourceMetadata:
    def test_metadata_document(self) -> None:
        response = Client().get("/.well-known/oauth-protected-resource/oauth-mcp")
        assert response.status_code == 200
        data = response.json()
        assert data["resource"] == "https://testserver/oauth-mcp"
        assert data["authorization_servers"] == ["https://auth.example.com"]
        assert data["bearer_methods_supported"] == ["header"]
        assert data["scopes_supported"] == ["read"]

    def test_metadata_defaults_authorization_servers_to_origin(self) -> None:
        # With no authorization_servers set, the app is its own auth server.
        response = Client().get(
            "/.well-known/oauth-protected-resource/oauth-mcp-sameapp"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["resource"] == "https://testserver/oauth-mcp-sameapp"
        assert data["authorization_servers"] == ["https://testserver"]
        assert "scopes_supported" not in data
