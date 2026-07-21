from __future__ import annotations

import hmac
from typing import cast

from plain.mcp import (
    MCPProtectedResourceView,
    MCPTool,
    MCPUnauthorized,
    MCPView,
    OAuthResourceServer,
    TokenInfo,
)
from plain.urls import Router, path


class Echo(MCPTool):
    """Return the input unchanged."""

    def __init__(self, text: str):
        self.text = text

    def run(self) -> str:
        return self.text


class Secret(MCPTool):
    """Return a secret value, only callable with a valid token."""

    def run(self) -> str:
        return "classified"


class PublicMCP(MCPView):
    name = "public"
    tools = [Echo]


class AuthedMCP(MCPView):
    """Bearer token auth via `before_request` override — mirrors the README recipe."""

    name = "authed"
    tools = [Secret]

    _token = "topsecret"

    def before_request(self) -> None:
        header = self.request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise MCPUnauthorized("Missing or invalid Authorization header")
        if not hmac.compare_digest(header[7:], self._token):
            raise MCPUnauthorized("Invalid auth token")


class BoomMCP(MCPView):
    """Raises a generic exception in before_request so handle_exception's
    5xx branch is exercised end to end."""

    name = "boom"
    tools: list[type[MCPTool]] = []

    def before_request(self) -> None:
        raise RuntimeError("mcp boom")


class RPCBoomMCP(MCPView):
    """Custom RPC method that raises so the `rpc {method}` span error path
    is exercised."""

    name = "rpc_boom"
    tools: list[type[MCPTool]] = []

    def rpc_boom(self, params: dict) -> dict:
        raise RuntimeError("rpc handler boom")


class WhoAmI(MCPTool):
    """Reflect the authenticated identity so tests can assert propagation."""

    def run(self) -> dict:
        mcp = cast("OAuthMCP", self.mcp)
        return {"user": mcp.user, "scopes": sorted(mcp.scopes)}


class OAuthMCP(OAuthResourceServer, MCPView):
    """OAuth-protected endpoint with a stub token validator."""

    name = "oauth"
    tools = [Secret, WhoAmI]

    def authenticate_token(self, token: str) -> TokenInfo | None:
        if token == "valid-token":
            return TokenInfo(user="alice", scopes=frozenset({"read"}))
        return None


class OAuthPRM(MCPProtectedResourceView):
    authorization_servers = ["https://auth.example.com"]
    oauth_scopes_supported = ["read"]


class OAuthPRMSameApp(MCPProtectedResourceView):
    """No authorization_servers set — defaults to this app's own origin."""


class AppRouter(Router):
    namespace = ""
    urls = [
        path("mcp", PublicMCP, name="public_mcp"),
        path("authed", AuthedMCP, name="authed_mcp"),
        path("boom", BoomMCP, name="boom_mcp"),
        path("rpc-boom", RPCBoomMCP, name="rpc_boom_mcp"),
        path("oauth-mcp", OAuthMCP, name="oauth_mcp"),
        path(
            ".well-known/oauth-protected-resource/oauth-mcp",
            OAuthPRM,
            name="oauth_prm",
        ),
        path(
            ".well-known/oauth-protected-resource/oauth-mcp-sameapp",
            OAuthPRMSameApp,
            name="oauth_prm_sameapp",
        ),
    ]
