"""OAuth resource-server tests: the 401 challenge, bearer auth, and RFC 9728
protected-resource metadata that let an MCP client discover the auth server.
"""

from __future__ import annotations

import json

from plain.test import Client


def _jsonrpc(method: str, params: dict | None = None, msg_id: int = 1) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}
    )


class TestChallenge:
    def test_missing_token_returns_401_with_www_authenticate(self) -> None:
        response = Client().post(
            "/oauth-mcp", data=_jsonrpc("initialize"), content_type="application/json"
        )
        assert response.status_code == 401
        challenge = response.headers["WWW-Authenticate"]
        assert challenge.startswith("Bearer ")
        # Points at this endpoint's protected-resource metadata (RFC 9728).
        assert (
            'resource_metadata="https://testserver/.well-known/'
            'oauth-protected-resource/oauth-mcp"' in challenge
        )

    def test_invalid_token_returns_401_with_challenge(self) -> None:
        client = Client(headers={"Authorization": "Bearer nope"})
        response = client.post(
            "/oauth-mcp", data=_jsonrpc("initialize"), content_type="application/json"
        )
        assert response.status_code == 401
        # RFC 6750: a supplied-but-rejected token is flagged invalid_token.
        assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]

    def test_valid_token_authenticates(self) -> None:
        client = Client(headers={"Authorization": "Bearer valid-token"})
        response = client.post(
            "/oauth-mcp", data=_jsonrpc("initialize"), content_type="application/json"
        )
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["result"]["protocolVersion"] == "2025-11-25"

    def test_lowercase_bearer_scheme_accepted(self) -> None:
        # RFC 7235: the auth-scheme is matched case-insensitively.
        client = Client(headers={"Authorization": "bearer valid-token"})
        response = client.post(
            "/oauth-mcp", data=_jsonrpc("initialize"), content_type="application/json"
        )
        assert response.status_code == 200

    def test_authenticated_tool_call_sees_user_and_scopes(self) -> None:
        # The headline contract: a tool reads self.mcp.user / .scopes end to end.
        client = Client(headers={"Authorization": "Bearer valid-token"})
        response = client.post(
            "/oauth-mcp",
            data=_jsonrpc("tools/call", {"name": "WhoAmI", "arguments": {}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = json.loads(response.content)
        result = json.loads(body["result"]["content"][0]["text"])
        assert result == {"user": "alice", "scopes": ["read"]}


class TestProtectedResourceMetadata:
    def test_metadata_document(self) -> None:
        response = Client().get("/.well-known/oauth-protected-resource/oauth-mcp")
        assert response.status_code == 200
        data = json.loads(response.content)
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
        data = json.loads(response.content)
        assert data["resource"] == "https://testserver/oauth-mcp-sameapp"
        assert data["authorization_servers"] == ["https://testserver"]
        assert "scopes_supported" not in data
