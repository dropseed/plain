"""HTTP-layer tests: MCPView, authentication, transport semantics.

Pure protocol behavior is tested in test_mcp.py; this file exercises the
Streamable HTTP transport via plain.test.Client.
"""

from __future__ import annotations

import json

from opentelemetry.trace import SpanKind, StatusCode

from plain.test import Client, capture_spans


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
            body=_jsonrpc("initialize"),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        assert body["result"]["protocolVersion"] == "2025-11-25"

    def test_initialize_echoes_supported_requested_version(self) -> None:
        # MCP version negotiation: a supported requested version is echoed back.
        client = Client()
        response = client.post(
            "/mcp",
            body=_jsonrpc("initialize", {"protocolVersion": "2025-06-18"}),
            content_type="application/json",
        )
        assert json.loads(response.content)["result"]["protocolVersion"] == "2025-06-18"

    def test_initialize_offers_preferred_for_unsupported_version(self) -> None:
        # An unsupported (or absent) requested version gets the server's preferred one.
        client = Client()
        response = client.post(
            "/mcp",
            body=_jsonrpc("initialize", {"protocolVersion": "1999-01-01"}),
            content_type="application/json",
        )
        assert json.loads(response.content)["result"]["protocolVersion"] == "2025-11-25"

    def test_unsupported_protocol_version_header_returns_400(self) -> None:
        # Spec MUST: an unsupported MCP-Protocol-Version header is rejected.
        client = Client(headers={"MCP-Protocol-Version": "1999-01-01"})
        response = client.post(
            "/mcp", body=_jsonrpc("ping"), content_type="application/json"
        )
        assert response.status_code == 400
        assert (
            json.loads(response.content)["error"]["code"] == -32600
        )  # INVALID_REQUEST

    def test_supported_protocol_version_header_accepted(self) -> None:
        client = Client(headers={"MCP-Protocol-Version": "2025-06-18"})
        response = client.post(
            "/mcp", body=_jsonrpc("ping"), content_type="application/json"
        )
        assert response.status_code == 200

    def test_post_tools_call(self) -> None:
        client = Client()
        response = client.post(
            "/mcp",
            body=_jsonrpc("tools/call", {"name": "Echo", "arguments": {"text": "hi"}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        body = json.loads(response.content)
        assert body["result"]["content"][0]["text"] == "hi"

    def test_post_notification_returns_202(self) -> None:
        """A JSON-RPC notification (no id) is acknowledged with 202, no body."""
        client = Client()
        response = client.post(
            "/mcp",
            body=json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            ),
            content_type="application/json",
        )
        assert response.status_code == 202


class TestUnhandledException:
    """MCPView 5xx responses carry the original exception so observability
    tooling can record it from the response."""

    def test_unhandled_exception_attaches_response_exception(self) -> None:
        client = Client(raise_request_exception=False)
        response = client.post(
            "/boom",
            body=_jsonrpc("ping"),
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

    def test_rpc_method_emits_server_span(self) -> None:
        with capture_spans() as otel_spans:
            client = Client()
            response = client.post(
                "/mcp",
                body=_jsonrpc("initialize"),
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

    def test_rpc_method_records_error_when_handler_fails(self) -> None:
        with capture_spans() as otel_spans:
            client = Client()
            response = client.post(
                "/rpc-boom",
                body=_jsonrpc("boom"),
                content_type="application/json",
            )
            # handle_message swallows handler exceptions into a JSON-RPC error
            # response with HTTP 200 — the failure surfaces on the span.
            assert response.status_code == 200
            body = json.loads(response.content)
            assert body["error"]["code"] == -32603

            rpc_spans = [
                s for s in otel_spans.get_finished_spans() if s.name == "rpc boom"
            ]
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
            body=_jsonrpc("ping"),
            content_type="application/json",
        )
        assert response.status_code == 401
        body = json.loads(response.content)
        assert body["error"]["code"] == -32001

    def test_wrong_bearer_rejected(self) -> None:
        client = Client(headers={"Authorization": "Bearer wrong-token"})
        response = client.post(
            "/authed",
            body=_jsonrpc("ping"),
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_correct_bearer_allowed(self) -> None:
        client = Client(headers={"Authorization": "Bearer topsecret"})
        response = client.post(
            "/authed",
            body=_jsonrpc("tools/call", {"name": "Secret", "arguments": {}}),
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
            body=_jsonrpc("tools/call", {"name": "Echo", "arguments": {"text": "hi"}}),
            content_type="application/json",
        )
        # Echo is on PublicMCP, not AuthedMCP → unknown tool error
        body = json.loads(response.content)
        assert body["result"]["isError"] is True
