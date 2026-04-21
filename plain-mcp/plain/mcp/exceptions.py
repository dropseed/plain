"""Exception types used by `plain.mcp`."""

from __future__ import annotations


class MCPUnauthorized(Exception):
    """Raised from `before_request` to reject an MCP request.

    `MCPView.handle_exception` catches this and returns a JSON-RPC 401
    response with the exception message as the error text.
    """


class MCPInvalidParams(Exception):
    """Raised from a JSON-RPC handler to signal bad caller params.

    The dispatcher translates this to a JSON-RPC `INVALID_PARAMS`
    (-32602) error rather than the blanket `INTERNAL_ERROR`.
    """
