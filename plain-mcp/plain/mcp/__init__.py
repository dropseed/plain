from __future__ import annotations

from .registry import mcp_resource, mcp_tool
from .urls import MCPRouter, MCPWellKnownRouter

__all__ = [
    "MCPRouter",
    "MCPWellKnownRouter",
    "mcp_resource",
    "mcp_tool",
]
