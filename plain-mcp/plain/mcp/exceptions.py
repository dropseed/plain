"""Exception types used by `plain.mcp`."""

from __future__ import annotations


class MCPUnauthorized(Exception):
    """Raised from `before_request` to reject an MCP request.

    `MCPView.handle_exception` catches this and returns a JSON-RPC 401
    response with the exception message as the error text. Pass
    `www_authenticate` to attach an RFC 9728 `WWW-Authenticate` challenge so an
    OAuth client knows where to discover the authorization server.
    """

    def __init__(self, message: str = "", *, www_authenticate: str | None = None):
        super().__init__(message)
        self.www_authenticate = www_authenticate


class MCPInvalidParams(Exception):
    """Raised from a JSON-RPC handler to signal bad caller params.

    The dispatcher translates this to a JSON-RPC `INVALID_PARAMS`
    (-32602) error rather than the blanket `INTERNAL_ERROR`.

    For a tool's `run()`, raise `MCPToolError` instead — tool execution
    errors travel in the result via `isError`, not as JSON-RPC errors.
    """


class MCPToolError(Exception):
    """Raised from a tool's `run()` to signal an expected, caller-facing failure.

    Bad input, not found, forbidden — failures the caller can understand and
    act on. The dispatcher returns the message to the client with
    `isError: true` (MCP's in-result error channel) and does *not* log it as a
    server exception, so expected failures don't pollute your error monitoring.

    Any other exception from `run()` is treated as an unexpected bug: logged
    server-side and returned as an opaque "Tool execution failed".
    """
