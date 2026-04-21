from __future__ import annotations

from app.mcp import ConformanceMCP  # ty: ignore[unresolved-import]

from plain.urls import Router, path


class AppRouter(Router):
    namespace = ""
    urls = [
        path("mcp/", ConformanceMCP, name="mcp"),
    ]
