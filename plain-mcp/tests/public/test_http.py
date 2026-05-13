"""HTTP-layer tests: MCPView, authentication, transport semantics.

Pure protocol behavior is tested in test_mcp.py; this file exercises the
Streamable HTTP transport via plain.test.Client.
"""

from __future__ import annotations

import json

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind, StatusCode

from plain.test import Client


def _jsonrpc(method: str, params: dict | None = None, msg_id: int = 1) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {},
        }
    )


class TestPublicEndpoint:
    """MCP mounted with a trivial allow-all authenticator."""

    def test_post_initialize(self) -> None:
        client = Client()
        response = client.post(
            "/mcp",
            data=_jsonrpc("initialize"),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        assert body["result"]["protocolVersion"] == "2025-03-26"

    def test_post_tools_call(self) -> None:
        client = Client()
        response = client.post(
            "/mcp",
            data=_jsonrpc("tools/call", {"name": "Echo", "arguments": {"text": "hi"}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["result"]["content"][0]["text"] == "hi"

    def test_post_notification_returns_204(self) -> None:
        """A JSON-RPC notification (no id) has no response body."""
        client = Client()
        response = client.post(
            "/mcp",
            data=json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            ),
            content_type="application/json",
        )
        assert response.status_code == 204


class TestUnhandledException:
    """MCPView 5xx responses carry the original exception so observability
    tooling can record it from the response."""

    def test_unhandled_exception_attaches_response_exception(self) -> None:
        client = Client(raise_request_exception=False)
        response = client.post(
            "/boom",
            data=_jsonrpc("ping"),
            content_type="application/json",
        )
        assert response.status_code == 500
        assert isinstance(response.exception, RuntimeError)
        body = json.loads(response.content)
        assert body["error"]["code"] == -32603  # INTERNAL_ERROR


class TestRPCMethodSpan:
    """Each RPC method dispatch gets a `rpc {method}` SERVER span — JSON-RPC
    is server-side request handling per OTel's RPC semconv. Without it,
    `handle_message` swallows handler failures into a JSON-RPC error with
    HTTP 200 — the outer HTTP SERVER span sees success and the failure is
    invisible to OTel-based exception tooling."""

    def test_rpc_method_emits_server_span(
        self, otel_spans: InMemorySpanExporter
    ) -> None:
        client = Client()
        response = client.post(
            "/mcp",
            data=_jsonrpc("initialize"),
            content_type="application/json",
        )
        assert response.status_code == 200

        rpc_spans = [
            s for s in otel_spans.get_finished_spans() if s.name == "rpc initialize"
        ]
        assert len(rpc_spans) == 1
        span = rpc_spans[0]
        assert span.kind == SpanKind.SERVER
        assert span.status.status_code == StatusCode.UNSET

    def test_rpc_method_records_error_when_handler_fails(
        self, otel_spans: InMemorySpanExporter
    ) -> None:
        client = Client()
        response = client.post(
            "/rpc-boom",
            data=_jsonrpc("boom"),
            content_type="application/json",
        )
        # handle_message swallows handler exceptions into a JSON-RPC error
        # response with HTTP 200 — the failure surfaces on the span.
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["error"]["code"] == -32603

        rpc_spans = [s for s in otel_spans.get_finished_spans() if s.name == "rpc boom"]
        assert len(rpc_spans) == 1
        span = rpc_spans[0]
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes is not None
        assert span.attributes["error.type"] == "RuntimeError"
        exception_events = [e for e in span.events if e.name == "exception"]
        assert exception_events


class TestAuthedEndpoint:
    """MCP mounted with an inline BearerAuth (see tests/app/urls.py)."""

    def test_missing_bearer_rejected(self) -> None:
        client = Client()
        response = client.post(
            "/authed",
            data=_jsonrpc("ping"),
            content_type="application/json",
        )
        assert response.status_code == 401
        body = json.loads(response.content)
        assert body["error"]["code"] == -32001

    def test_wrong_bearer_rejected(self) -> None:
        client = Client(headers={"Authorization": "Bearer wrong-token"})
        response = client.post(
            "/authed",
            data=_jsonrpc("ping"),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_correct_bearer_allowed(self) -> None:
        client = Client(headers={"Authorization": "Bearer topsecret"})
        response = client.post(
            "/authed",
            data=_jsonrpc("tools/call", {"name": "Secret", "arguments": {}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["result"]["content"][0]["text"] == "classified"

    def test_tools_isolated_between_endpoints(self) -> None:
        """Tools registered on one instance are not callable on another."""
        client = Client(headers={"Authorization": "Bearer topsecret"})
        response = client.post(
            "/authed",
            data=_jsonrpc("tools/call", {"name": "Echo", "arguments": {"text": "hi"}}),
            content_type="application/json",
        )
        # Echo is on PublicMCP, not AuthedMCP → unknown tool error
        body = json.loads(response.content)
        assert body["result"]["isError"] is True
