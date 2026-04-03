from __future__ import annotations

from .registry import mcp_resource, mcp_tool
from .urls import MCPRouter

__all__ = [
    "MCPRouter",
    "mcp_resource",
    "mcp_tool",
]
