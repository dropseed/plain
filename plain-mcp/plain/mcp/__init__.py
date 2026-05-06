from __future__ import annotations

from importlib.metadata import version

__version__ = version("plain.mcp")

from .exceptions import MCPInvalidParams, MCPUnauthorized
from .resources import MCPResource
from .tools import MCPTool
from .views import MCPView

__all__ = [
    "MCPInvalidParams",
    "MCPResource",
    "MCPTool",
    "MCPUnauthorized",
    "MCPView",
]
