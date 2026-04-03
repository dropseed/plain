from __future__ import annotations

from plain.urls import Router, path

from .views import MCPView


class MCPRouter(Router):
    namespace = "mcp"
    urls = [
        path("", MCPView, name="endpoint"),
    ]
