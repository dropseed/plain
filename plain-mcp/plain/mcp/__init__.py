from __future__ import annotations

from importlib.metadata import version

__version__ = version("plain.mcp")

from .exceptions import MCPInvalidParams, MCPUnauthorized
from .oauth import MCPProtectedResourceView, OAuthResourceServer, TokenInfo
from .resources import MCPResource
from .tools import MCPTool
from .views import MCPView

__all__ = [
    "MCPInvalidParams",
    "MCPProtectedResourceView",
    "MCPResource",
    "MCPTool",
    "MCPUnauthorized",
    "MCPView",
    "OAuthResourceServer",
    "TokenInfo",
]
