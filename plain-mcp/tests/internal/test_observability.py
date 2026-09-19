"""The `mcp.*` observability surface: routing facts stamped on the request
span, and the reject log for JSON-RPC error replies.

These pin instrumentation, not protocol behavior — the wire contract these
requests exercise is covered in `public/`. The scenario that motivated the
surface: a conformant classic client that also sent the `Mcp-Method` header
used to be misrouted onto the modern ladder, and the resulting 400 was
invisible server-side — no span attribute, no log, and a client that
swallows the body reports only "connection failed". The misrouting is
fixed; these facts are what would have made it a one-trace diagnosis.
"""

from __future__ import annotations

from typing import Any

from mcp_test_helpers import bare_post, mcp_post, mcp_post_raw
from opentelemetry import trace
from plain.mcp.exceptions import INVALID_PARAMS, METHOD_NOT_FOUND
from plain.mcp.views import META_PROTOCOL_VERSION, PROTOCOL_VERSION
from plain.test import CapturedLogs, capture_logs, capture_spans


def _rejects(logs: CapturedLogs) -> list[dict[str, Any]]:
    """The reject records' fields — `extra` lands as LogRecord attributes,
    so the record `__dict__` is where the structured context lives."""
    return [r.__dict__ for r in logs if r.getMessage() == "MCP request rejected"]


def _request_span(spans, path: str = "/mcp"):
    """The most recent request SERVER span — not the inner `rpc <method>` one."""
    found = [
        s
        for s in spans.get_finished_spans()
        if s.kind == trace.SpanKind.SERVER and s.name == f"POST {path}"
    ]
    assert found, f"no `POST {path}` SERVER span captured"
    return found[-1]


def test_classic_request_stamps_routing_facts() -> None:
    with capture_spans() as spans:
        response = bare_post(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
        )
    assert response.status_code == 200

    attrs = _request_span(spans).attributes
    assert attrs["mcp.method"] == "initialize"
    assert attrs["mcp.revision"] == "classic"
    assert attrs["mcp.method_header_present"] is False
    assert attrs["mcp.meta_protocol_version_present"] is False
    assert "mcp.protocol_version_header" not in attrs
    assert "mcp.error.code" not in attrs


def test_modern_request_stamps_routing_facts() -> None:
    with capture_spans() as spans:
        response = mcp_post("/mcp", "tools/list")
    assert response.status_code == 200

    attrs = _request_span(spans).attributes
    assert attrs["mcp.method"] == "tools/list"
    assert attrs["mcp.revision"] == "modern"
    assert attrs["mcp.method_header_present"] is True
    assert attrs["mcp.meta_protocol_version_present"] is True
    assert attrs["mcp.protocol_version_header"] == PROTOCOL_VERSION
    assert "mcp.error.code" not in attrs


def test_notification_stamps_method() -> None:
    with capture_spans() as spans:
        response = bare_post(
            "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
    assert response.status_code == 202

    attrs = _request_span(spans).attributes
    assert attrs["mcp.method"] == "notifications/initialized"
    # Acknowledged before classification, so no revision was decided.
    assert "mcp.revision" not in attrs


def test_classic_with_extra_headers_stamps_them() -> None:
    # claude.ai's connector shape: no `_meta`, the negotiated classic
    # version header, plus an extra `Mcp-Method` header. Served classically
    # (test_classic.py owns that contract) — here we pin that the span still
    # records the header facts, because revision-vs-headers is exactly what
    # a "why was this client rejected?" investigation reads first.
    with capture_spans() as spans, capture_logs("plain.mcp") as mcp_log:
        response = bare_post(
            "/mcp",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={
                "MCP-Protocol-Version": "2025-11-25",
                "Mcp-Method": "tools/list",
            },
        )
    assert response.status_code == 200

    attrs = _request_span(spans).attributes
    assert attrs["mcp.method"] == "tools/list"
    assert attrs["mcp.revision"] == "classic"
    assert attrs["mcp.method_header_present"] is True
    assert attrs["mcp.protocol_version_header"] == "2025-11-25"
    assert "mcp.error.code" not in attrs
    assert not _rejects(mcp_log)


def test_modern_ladder_reject_is_observable() -> None:
    # A request that does declare the modern `_meta` still walks the ladder,
    # and a rung failure lands on the span and in the log.
    with capture_spans() as spans, capture_logs("plain.mcp") as mcp_log:
        response = mcp_post_raw(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": {META_PROTOCOL_VERSION: PROTOCOL_VERSION}},
            },
        )
    assert response.status_code == 400

    attrs = _request_span(spans).attributes
    assert attrs["mcp.method"] == "tools/list"
    assert attrs["mcp.revision"] == "modern"
    assert attrs["mcp.protocol_version_header"] == PROTOCOL_VERSION
    assert attrs["mcp.error.code"] == INVALID_PARAMS
    assert "clientCapabilities" in attrs["mcp.error.message"]

    (record,) = _rejects(mcp_log)
    assert record["error_code"] == INVALID_PARAMS
    assert "clientCapabilities" in record["error_message"]
    assert record["method"] == "tools/list"
    assert record["revision"] == "modern"
    assert record["protocol_version_header"] == PROTOCOL_VERSION


def test_classic_error_reply_is_observable() -> None:
    # Classic errors ride HTTP 200, so span + log are the only server-side
    # trace of them at all.
    with capture_spans() as spans, capture_logs("plain.mcp") as mcp_log:
        response = bare_post(
            "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "prompts/list"}
        )
    assert response.status_code == 200
    assert response.json_data["error"]["code"] == METHOD_NOT_FOUND

    attrs = _request_span(spans).attributes
    assert attrs["mcp.revision"] == "classic"
    assert attrs["mcp.error.code"] == METHOD_NOT_FOUND

    (record,) = _rejects(mcp_log)
    assert record["error_code"] == METHOD_NOT_FOUND
    assert record["method"] == "prompts/list"


def test_internal_error_is_stamped_but_not_relogged() -> None:
    # -32603 already logs with a traceback in `handle_message` — the reject
    # log stays quiet so the failure isn't reported twice.
    with capture_spans() as spans, capture_logs("plain.mcp") as mcp_log:
        response = mcp_post("/rpc-boom", "boom")
    assert response.status_code == 200
    assert response.json_data["error"]["code"] == -32603

    attrs = _request_span(spans, path="/rpc-boom").attributes
    assert attrs["mcp.error.code"] == -32603
    assert not _rejects(mcp_log)
