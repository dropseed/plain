from __future__ import annotations

from plain.urls import Router, path

from .views import MCPView, ProtectedResourceMetadataView


class MCPRouter(Router):
    namespace = "mcp"
    urls = [
        path("", MCPView, name="endpoint"),
    ]


class MCPWellKnownRouter(Router):
    """Mount at .well-known/ in your root router for MCP OAuth discovery."""

    namespace = ""
    urls = [
        path(
            "oauth-protected-resource",
            ProtectedResourceMetadataView,
            name="oauth_protected_resource_metadata",
        ),
    ]
