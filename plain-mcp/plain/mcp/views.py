"""MCP Streamable HTTP transport views.

Implements the MCP Streamable HTTP transport (2025-03-26 spec):
- POST: Client sends JSON-RPC request, server responds with JSON or SSE
- GET: Client opens SSE stream for server-initiated notifications
- DELETE: Client terminates session
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from plain.http import (
    AsyncStreamingResponse,
    JsonResponse,
    Request,
    Response,
    ResponseBase,
)
from plain.logs import get_framework_logger
from plain.packages import packages_registry
from plain.runtime import settings
from plain.views.base import View

from .protocol import MCPServer, generate_session_id
from .registry import mcp_registry

logger = get_framework_logger("plain.mcp")


def _ensure_discovered() -> None:
    """Auto-discover mcp modules from installed packages (runs once)."""
    if not getattr(_ensure_discovered, "_done", False):
        packages_registry.autodiscover_modules("mcp", include_app=True)
        _ensure_discovered._done = True  # type: ignore[attr-defined]


def _check_auth(request: Request) -> ResponseBase | None:
    """Return an error response if auth fails, or None if OK."""
    token = settings.MCP_AUTH_TOKEN
    if not token:
        # No token configured — allow all (development mode)
        return None

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32001,
                    "message": "Missing or invalid Authorization header",
                },
            },
            status_code=401,
        )

    provided_token = auth_header[7:]  # len("Bearer ") == 7
    if provided_token != token:
        return JsonResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32001, "message": "Invalid auth token"},
            },
            status_code=401,
        )

    return None


class MCPView(View):
    """Streamable HTTP transport endpoint for MCP.

    Handles POST (JSON-RPC requests), GET (SSE stream), and DELETE (session end).
    """

    def get_response(self) -> ResponseBase:
        _ensure_discovered()

        auth_error = _check_auth(self.request)
        if auth_error:
            return auth_error

        return super().get_response()

    def post(self) -> ResponseBase:
        """Handle a JSON-RPC request from the MCP client."""
        server = MCPServer(mcp_registry)

        body = self.request.body
        response = server.handle_message(body)

        if response is None:
            # Notification — accepted, no content
            return Response(status_code=204)

        session_id = generate_session_id()
        json_response = JsonResponse(response)
        json_response.headers["Mcp-Session-Id"] = session_id
        return json_response

    def get(self) -> ResponseBase:
        """Open an SSE stream for server-initiated notifications.

        For now, this keeps the connection alive with periodic keepalives.
        Server push notifications can be added later.
        """
        return AsyncStreamingResponse(
            streaming_content=self._keepalive_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Mcp-Session-Id": generate_session_id(),
            },
        )

    def delete(self) -> Response:
        """Terminate an MCP session."""
        return Response(status_code=200)

    async def _keepalive_stream(self) -> AsyncIterator[str]:
        """Yield SSE keepalive comments to keep the connection open."""
        import asyncio

        # Send an initial endpoint event so clients know we're alive
        yield _sse_event(
            {"jsonrpc": "2.0", "method": "notifications/ready", "params": {}}
        )

        while True:
            await asyncio.sleep(30)
            yield ": keepalive\n\n"


def _sse_event(data: dict[str, Any], *, event: str | None = None) -> str:
    """Format a dict as a single SSE event."""
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"
