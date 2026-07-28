"""JSON-RPC error codes, the error envelope, and the exceptions `plain.mcp` raises."""

from __future__ import annotations

from typing import Any

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020
MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
UNSUPPORTED_PROTOCOL_VERSION = -32022


def _error_response(
    msg_id: Any, code: int, message: str, *, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": error}


class _ProtocolError(Exception):
    """A protocol-level failure that ends the request where it's raised.

    Carries the JSON-RPC code and payload and nothing else —
    `ERROR_CODE_HTTP_STATUS` in `views` maps the code to a status, so a code
    can't pick up a different one depending on which raise site produced it.
    """

    def __init__(self, code: int, message: str, *, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.data = data

    def as_response(self, msg_id: Any) -> dict[str, Any]:
        return _error_response(msg_id, self.code, str(self), data=self.data)


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


class MCPInvalidParams(_ProtocolError):
    """Raised from a JSON-RPC handler to signal bad caller params.

    Answers with a JSON-RPC `INVALID_PARAMS` (-32602) at HTTP 400 rather than
    the blanket `INTERNAL_ERROR`, and — being a protocol error — is never
    logged or recorded as a server failure.

    Pass `data` to attach a structured payload, so the client doesn't have to
    parse the message to learn what was wrong:

        raise MCPInvalidParams(f"Unknown resource: {uri}", data={"uri": uri})

    For a tool's `run()`, raise `MCPToolError` instead — tool execution
    errors travel in the result via `isError`, not as JSON-RPC errors.
    """

    def __init__(self, message: str = "", *, data: dict[str, Any] | None = None):
        super().__init__(INVALID_PARAMS, message, data=data)


class MCPToolError(Exception):
    """Raised from a tool's `run()` to signal an expected, caller-facing failure.

    Bad input, not found, forbidden — failures the caller can understand and
    act on. The dispatcher returns the message to the client with
    `isError: true` (MCP's in-result error channel) and does *not* log it as a
    server exception, so expected failures don't pollute your error monitoring.

    Any other exception from `run()` is treated as an unexpected bug: logged
    server-side and returned as an opaque "Tool execution failed".
    """
