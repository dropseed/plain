"""MCP Streamable HTTP transport views.

Implements the MCP Streamable HTTP transport (2025-03-26 spec):
- POST: Client sends JSON-RPC request, server responds with JSON or SSE
- GET: Client opens SSE stream for server-initiated notifications
- DELETE: Client terminates session
"""

from __future__ import annotations

import functools
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
from plain.runtime import settings
from plain.views.base import View

from .protocol import MCPServer
from .registry import mcp_registry

_server = MCPServer(mcp_registry)


@functools.cache
def _has_oauth_provider() -> bool:
    """Check whether plain.oauth_provider is installed (cached after first call)."""
    try:
        from plain.oauth_provider.models import AccessToken  # noqa: F401

        return True
    except ImportError:
        return False


def _check_auth(request: Request) -> ResponseBase | None:
    """Return an error response if auth fails, or None if OK.

    Checks in order:
    1. If MCP_AUTH_TOKEN is set, validate against that (simple shared token).
    2. If plain.oauth_provider is installed, validate as an OAuth access token.
    3. If neither is configured, allow all requests (development mode).
    """
    auth_header = request.headers.get("Authorization", "")
    bearer_token = ""
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:]

    # 1. Simple shared token check
    static_token = settings.MCP_AUTH_TOKEN
    if static_token:
        if not bearer_token:
            return _auth_error("Missing or invalid Authorization header")
        if bearer_token != static_token:
            return _auth_error("Invalid auth token")
        return None

    # 2. OAuth access token check (if plain-oauth-provider is installed)
    if _has_oauth_provider():
        from plain.oauth_provider.models import AccessToken

        if not bearer_token:
            return _auth_error("Missing or invalid Authorization header")

        try:
            access_token = AccessToken.query.get(token=bearer_token)
            if access_token.is_valid():
                return None
            return _auth_error("Access token expired or revoked")
        except AccessToken.DoesNotExist:
            return _auth_error("Invalid access token")

    # No auth configured — allow all (development mode)
    return None


def _auth_error(message: str) -> JsonResponse:
    return JsonResponse(
        {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32001, "message": message},
        },
        status_code=401,
    )


class ProtectedResourceMetadataView(View):
    """RFC 9728: OAuth 2.0 Protected Resource Metadata.

    Served at /.well-known/oauth-protected-resource to tell MCP clients
    where to obtain authorization. Only useful when plain-oauth-provider
    is installed.
    """

    def get(self) -> ResponseBase:
        scheme = self.request.server_scheme
        host = self.request.host
        base = f"{scheme}://{host}"

        metadata: dict[str, Any] = {
            "resource": base,
            "authorization_servers": [f"{base}/.well-known/oauth-authorization-server"],
        }

        return JsonResponse(metadata)


class MCPView(View):
    """Streamable HTTP transport endpoint for MCP.

    Handles POST (JSON-RPC requests), GET (SSE stream), and DELETE (session end).
    """

    def get_response(self) -> ResponseBase:
        auth_error = _check_auth(self.request)
        if auth_error:
            return auth_error

        return super().get_response()

    def post(self) -> ResponseBase:
        """Handle a JSON-RPC request from the MCP client."""
        body = self.request.body
        response = _server.handle_message(body)

        if response is None:
            return Response(status_code=204)

        return JsonResponse(response)

    def get(self) -> ResponseBase:
        """Open an SSE stream for server-initiated notifications."""
        return AsyncStreamingResponse(
            streaming_content=self._keepalive_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    def delete(self) -> Response:
        """Terminate an MCP session."""
        return Response(status_code=200)

    async def _keepalive_stream(self) -> AsyncIterator[str]:
        """Yield SSE keepalive comments to keep the connection open."""
        import asyncio

        yield _sse_event(
            {"jsonrpc": "2.0", "method": "notifications/ready", "params": {}}
        )

        while True:
            await asyncio.sleep(30)
            yield ": keepalive\n\n"


def _sse_event(data: dict[str, Any]) -> str:
    """Format a dict as a single SSE event."""
    return f"data: {json.dumps(data)}\n\n"
