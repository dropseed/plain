from __future__ import annotations

from plain.mcp import MCPRouter
from plain.urls import Router, include


class AppRouter(Router):
    namespace = ""
    urls = [
        include("mcp/", MCPRouter),
    ]
