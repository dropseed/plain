"""HTTP-layer tests: MCPView, authentication, transport semantics.

Dispatch and result shapes are tested in test_mcp.py; this file exercises the
Streamable HTTP transport via plain.test.Client — everything that only has an
answer once there's a real request with real headers and a real status code.

The `mcp_post` fixture (tests/conftest.py) builds the body and headers.
"""

from __future__ import annotations

import base64

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind, StatusCode

from plain.mcp.views import (
    META_CLIENT_CAPABILITIES,
    META_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
)
from plain.test import Client


class TestPublicEndpoint:
    """MCP mounted with a trivial allow-all authenticator."""

    def test_post_server_discover(self, mcp_post) -> None:
        response = mcp_post("/mcp", "server/discover")
        assert response.status_code == 200
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 1
        assert body["result"]["supportedVersions"] == [PROTOCOL_VERSION]

    def test_post_tools_call(self, mcp_post) -> None:
        response = mcp_post(
            "/mcp", "tools/call", {"name": "Echo", "arguments": {"text": "hi"}}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["content"][0]["text"] == "hi"

    def test_post_notification_returns_202(self, mcp_post_raw) -> None:
        """A JSON-RPC notification (no id) is acknowledged with 202, no body.

        The spec doesn't define header or `_meta` requirements for
        notifications, so none are sent here.
        """
        response = mcp_post_raw(
            "/mcp",
            {"jsonrpc": "2.0", "method": "notifications/progress"},
            headers={"MCP-Protocol-Version": None, "Mcp-Method": None},
        )
        assert response.status_code == 202
        assert not response.content

    def test_post_malformed_notification_still_returns_202(self, mcp_post_raw) -> None:
        """A notification is never answered — not even to reject it.

        By-position params are legal JSON-RPC that MCP methods don't accept,
        so this would be a `-32602` had it carried an `id`. Without one there
        is nobody to tell, and the spec's "MUST NOT reply to a notification"
        wins over saying so.
        """
        response = mcp_post_raw(
            "/mcp",
            {"jsonrpc": "2.0", "method": "tools/list", "params": []},
            headers={"MCP-Protocol-Version": None, "Mcp-Method": None},
        )
        assert response.status_code == 202
        assert not response.content

    def test_invalid_params_reply_keeps_the_request_id(self, mcp_post_raw) -> None:
        """An error a client can't match to its request is an error it can't act on.

        The id is readable here — the body parsed and named one — so JSON-RPC
        requires it echoed back. Only a request whose id can't be read at all
        (unparseable body, not an object) answers with a null id.
        """
        response = mcp_post_raw(
            "/mcp",
            {"jsonrpc": "2.0", "id": 37, "method": "tools/list", "params": []},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["id"] == 37
        assert body["error"]["code"] == -32602

    def test_unknown_method_returns_404(self, mcp_post) -> None:
        # Spec MUST: an unknown method is a 404 carrying the JSON-RPC error,
        # which is how a client distinguishes it from a missing URL.
        response = mcp_post("/mcp", "bogus/method")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == -32601

    def test_underscore_method_name_rejected(self, mcp_post) -> None:
        """`tools_list` must not reach the `tools/list` → `rpc_tools_list` handler.

        JSON-RPC method names in MCP use `/` as the separator, so an
        underscore in a raw method name is never valid — rejecting it keeps
        the `/` → `_` rewrite collision-free.
        """
        response = mcp_post("/mcp", "tools_list")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == -32601

    def test_get_is_not_allowed(self) -> None:
        # No GET stream in a stateless server — there is nothing to resume.
        assert Client().get("/mcp").status_code == 405

    def test_delete_is_not_allowed(self) -> None:
        # No sessions, so no session to delete.
        assert Client().delete("/mcp").status_code == 405


class TestRequestMeta:
    """Every request restates its protocol version and the client's
    capabilities — there is no handshake to establish them once."""

    def _post_with_meta(
        self, mcp_post_raw, meta: dict, *, headers: dict[str, str | None] | None = None
    ):
        """POST tools/list with a hand-built `_meta`."""
        return mcp_post_raw(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": meta},
            },
            headers=headers,
        )

    def test_missing_meta_is_invalid_params(self, mcp_post_raw) -> None:
        # The MCP-Protocol-Version header explicitly declares 2026-07-28, so
        # this is a modern client with a broken envelope and the ladder says
        # exactly what's missing. Only that declared version selects the
        # modern path for a `_meta`-less request — any other header shape
        # routes to the compatibility branch (test_classic.py).
        response = self._post_with_meta(mcp_post_raw, {})
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32602
        assert META_PROTOCOL_VERSION in body["error"]["message"]

    def test_missing_client_capabilities_is_invalid_params(self, mcp_post_raw) -> None:
        response = self._post_with_meta(
            mcp_post_raw, {META_PROTOCOL_VERSION: PROTOCOL_VERSION}
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32602
        assert META_CLIENT_CAPABILITIES in body["error"]["message"]

    def test_unsupported_protocol_version_rejected(self, mcp_post_raw) -> None:
        response = self._post_with_meta(
            mcp_post_raw,
            {META_PROTOCOL_VERSION: "2025-06-18", META_CLIENT_CAPABILITIES: {}},
            # Kept consistent with the body so the header rung passes and the
            # version rung is what answers.
            headers={"MCP-Protocol-Version": "2025-06-18"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32022
        assert body["error"]["data"] == {
            "supported": [PROTOCOL_VERSION],
            "requested": "2025-06-18",
        }

    def test_meta_is_checked_before_headers(self, mcp_post_raw) -> None:
        # Both wrong at once: no `_meta` and no Mcp-Method header. `_meta` is
        # the request's own statement of what it is, and the header check
        # compares against the version `_meta` resolves to — so `_meta` is
        # validated first and its error is the one reported.
        response = self._post_with_meta(mcp_post_raw, {}, headers={"Mcp-Method": None})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32602  # not -32020


class TestTransportHeaders:
    """Every request mirrors its method (and target) into headers so
    infrastructure can route and authorize without parsing the body."""

    def test_missing_mcp_method_header_rejected(self, mcp_post) -> None:
        response = mcp_post("/mcp", "tools/list", headers={"Mcp-Method": None})
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32020
        assert "Mcp-Method" in body["error"]["message"]

    def test_mcp_method_header_mismatch_rejected(self, mcp_post) -> None:
        response = mcp_post("/mcp", "tools/list", headers={"Mcp-Method": "tools/call"})
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32020
        assert (
            body["error"]["message"] == "Header mismatch: Mcp-Method header value "
            "'tools/call' does not match body value 'tools/list'"
        )

    def test_missing_protocol_version_header_rejected(self, mcp_post) -> None:
        response = mcp_post(
            "/mcp", "tools/list", headers={"MCP-Protocol-Version": None}
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32020
        assert "MCP-Protocol-Version" in body["error"]["message"]

    def test_protocol_version_header_must_match_meta(self, mcp_post) -> None:
        response = mcp_post(
            "/mcp", "tools/list", headers={"MCP-Protocol-Version": "2025-06-18"}
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32020
        assert "2025-06-18" in body["error"]["message"]

    def test_mcp_name_header_required_for_tools_call(self, mcp_post) -> None:
        response = mcp_post(
            "/mcp",
            "tools/call",
            {"name": "Echo", "arguments": {"text": "hi"}},
            headers={"Mcp-Name": None},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32020
        assert "Mcp-Name" in body["error"]["message"]

    def test_mcp_name_header_mismatch_rejected(self, mcp_post) -> None:
        response = mcp_post(
            "/mcp",
            "tools/call",
            {"name": "Echo", "arguments": {"text": "hi"}},
            headers={"Mcp-Name": "Secret"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32020
        assert (
            body["error"]["message"] == "Header mismatch: Mcp-Name header value "
            "'Secret' does not match body value 'Echo'"
        )

    def test_base64_encoded_mcp_name_is_decoded_before_comparing(
        self, mcp_post
    ) -> None:
        # A name that isn't header-safe ASCII travels base64-encoded inside a
        # sentinel; the server compares the decoded value against the body.
        uri = "notes://caffè"
        encoded = base64.b64encode(uri.encode("utf-8")).decode("ascii")
        response = mcp_post(
            "/mcp",
            "resources/read",
            {"uri": uri},
            headers={"Mcp-Name": f"=?base64?{encoded}?="},
        )
        # The URI decodes and matches, so this gets past the transport check
        # and fails on the resource not existing — a different error entirely.
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == -32602
        assert "Unknown resource" in body["error"]["message"]
        # SEP-2164: the error echoes what wasn't found.
        assert body["error"]["data"] == {"uri": uri}

    def test_header_case_is_ignored(self, mcp_post) -> None:
        response = mcp_post(
            "/mcp",
            "tools/list",
            headers={
                "Mcp-Method": None,
                "MCP-Protocol-Version": None,
                "mcp-method": "tools/list",
                "mcp-protocol-version": PROTOCOL_VERSION,
            },
        )
        assert response.status_code == 200


class TestMalformedRequests:
    def test_parse_error(self, mcp_post_raw) -> None:
        response = mcp_post_raw("/mcp", "not json")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32700

    def test_non_object_request_rejected(self, mcp_post_raw) -> None:
        response = mcp_post_raw("/mcp", "[1, 2, 3]")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32600

    def test_missing_jsonrpc_version_rejected(self, mcp_post_raw) -> None:
        response = mcp_post_raw("/mcp", {"id": 1, "method": "tools/list"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32600

    def test_wrong_jsonrpc_version_rejected(self, mcp_post_raw) -> None:
        response = mcp_post_raw(
            "/mcp", {"jsonrpc": "1.0", "id": 1, "method": "tools/list"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32600

    def test_array_params_rejected(self, mcp_post_raw) -> None:
        response = mcp_post_raw(
            "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32602

    def test_removed_methods_are_unknown_methods(self, mcp_post) -> None:
        # SEP-2575: on the modern path, a method this revision removed answers
        # like any other unknown method — 404 / -32601 — naming the version we
        # speak. Only the *modern* path: a classic client sends these without
        # the modern envelope and is served by the compatibility branch
        # instead (test_classic.py).
        for method in ("initialize", "ping", "logging/setLevel"):
            response = mcp_post("/mcp", method)
            assert response.status_code == 404, method
            body = response.json()
            assert body["error"]["code"] == -32601, method
            assert PROTOCOL_VERSION in body["error"]["message"], method
            assert body["error"]["data"] == {"supportedVersions": [PROTOCOL_VERSION]}


class TestUnhandledException:
    """MCPView 5xx responses carry the original exception so observability
    tooling can record it from the response."""

    def test_unhandled_exception_attaches_response_exception(self, mcp_post) -> None:
        client = Client(raise_request_exception=False)
        response = mcp_post("/boom", "tools/list", client=client)
        assert response.status_code == 500
        assert isinstance(response.exception, RuntimeError)
        body = response.json()
        assert body["error"]["code"] == -32603  # INTERNAL_ERROR


class TestRPCMethodSpan:
    """Each RPC method dispatch gets a `rpc {method}` SERVER span — JSON-RPC
    is server-side request handling per OTel's RPC semconv. Without it,
    `handle_message` swallows handler failures into a JSON-RPC error with
    HTTP 200 — the outer HTTP SERVER span sees success and the failure is
    invisible to OTel-based exception tooling."""

    def test_rpc_method_emits_server_span(
        self, mcp_post, otel_spans: InMemorySpanExporter
    ) -> None:
        response = mcp_post("/mcp", "tools/list")
        assert response.status_code == 200

        rpc_spans = [
            s for s in otel_spans.get_finished_spans() if s.name == "rpc tools/list"
        ]
        assert len(rpc_spans) == 1
        span = rpc_spans[0]
        assert span.kind == SpanKind.SERVER
        assert span.status.status_code == StatusCode.UNSET

    def test_rpc_method_records_error_when_handler_fails(
        self, mcp_post, otel_spans: InMemorySpanExporter
    ) -> None:
        response = mcp_post("/rpc-boom", "boom")
        # handle_message swallows handler exceptions into a JSON-RPC error
        # response with HTTP 200 — the failure surfaces on the span.
        assert response.status_code == 200
        body = response.json()
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

    def test_missing_bearer_rejected(self, mcp_post) -> None:
        response = mcp_post("/authed", "tools/list")
        assert response.status_code == 401
        body = response.json()
        # The status is the code: the reserved -320xx range is the protocol's
        # (-32001 is a request timeout there), so an auth failure can't borrow
        # from it without a client misreading the answer.
        assert body["error"]["code"] == 401

    def test_wrong_bearer_rejected(self, mcp_post) -> None:
        client = Client(headers={"Authorization": "Bearer wrong-token"})
        response = mcp_post("/authed", "tools/list", client=client)
        assert response.status_code == 401

    def test_correct_bearer_allowed(self, mcp_post) -> None:
        client = Client(headers={"Authorization": "Bearer topsecret"})
        response = mcp_post(
            "/authed", "tools/call", {"name": "Secret", "arguments": {}}, client=client
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["content"][0]["text"] == "classified"

    def test_tools_isolated_between_endpoints(self, mcp_post) -> None:
        """Tools registered on one instance are not callable on another."""
        client = Client(headers={"Authorization": "Bearer topsecret"})
        response = mcp_post(
            "/authed",
            "tools/call",
            {"name": "Echo", "arguments": {"text": "hi"}},
            client=client,
        )
        # Echo is on PublicMCP, not AuthedMCP → unknown tool error
        body = response.json()
        assert body["result"]["isError"] is True
