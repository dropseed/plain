from __future__ import annotations

import hmac

from plain.mcp import MCPTool, MCPUnauthorized, MCPView
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
    """Bearer token auth via `check_auth` override — mirrors the README recipe."""

    name = "authed"
    tools = [Secret]

    _token = "topsecret"

    def before_request(self) -> None:
        header = self.request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise MCPUnauthorized("Missing or invalid Authorization header")
        if not hmac.compare_digest(header[7:], self._token):
            raise MCPUnauthorized("Invalid auth token")


class AppRouter(Router):
    namespace = ""
    urls = [
        path("mcp/", PublicMCP, name="public_mcp"),
        path("authed/", AuthedMCP, name="authed_mcp"),
    ]
