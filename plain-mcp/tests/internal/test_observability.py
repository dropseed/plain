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

import logging
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from plain.mcp.exceptions import INVALID_PARAMS, METHOD_NOT_FOUND
from plain.mcp.views import META_PROTOCOL_VERSION, PROTOCOL_VERSION
from plain.test import Client


class _ListHandler(logging.Handler):
    """Captures records into a list regardless of logger propagation.

    We can't rely on pytest's `caplog` because `configure_logging` sets
    `propagate=False` on `plain` loggers; once another test has called
    it, records never reach caplog's root-attached handler.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def mcp_log():
    logger = logging.getLogger("plain.mcp")
    handler = _ListHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _rejects(handler: _ListHandler) -> list[dict[str, Any]]:
    """The reject records' fields — `extra` lands as LogRecord attributes,
    so the record `__dict__` is where the structured context lives."""
    return [
        r.__dict__ for r in handler.records if r.getMessage() == "MCP request rejected"
    ]


def _request_span(otel_spans: InMemorySpanExporter, path: str = "/mcp"):
    """The most recent request SERVER span — not the inner `rpc <method>` one."""
    spans = [
        s
        for s in otel_spans.get_finished_spans()
        if s.kind == trace.SpanKind.SERVER and s.name == f"POST {path}"
    ]
    assert spans, f"no `POST {path}` SERVER span captured"
    return spans[-1]


def _bare_post(
    path: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
):
    """POST bare JSON-RPC — no `_meta` envelope, only the headers given."""
    return Client().post(
        path, data=body, content_type="application/json", headers=headers or {}
    )


def test_classic_request_stamps_routing_facts(
    otel_spans: InMemorySpanExporter,
) -> None:
    response = _bare_post(
        "/mcp",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
    )
    assert response.status_code == 200

    attrs = _request_span(otel_spans).attributes
    assert attrs["mcp.method"] == "initialize"
    assert attrs["mcp.revision"] == "classic"
    assert attrs["mcp.method_header_present"] is False
    assert attrs["mcp.meta_protocol_version_present"] is False
    assert "mcp.protocol_version_header" not in attrs
    assert "mcp.error.code" not in attrs


def test_modern_request_stamps_routing_facts(
    otel_spans: InMemorySpanExporter, mcp_post
) -> None:
    response = mcp_post("/mcp", "tools/list")
    assert response.status_code == 200

    attrs = _request_span(otel_spans).attributes
    assert attrs["mcp.method"] == "tools/list"
    assert attrs["mcp.revision"] == "modern"
    assert attrs["mcp.method_header_present"] is True
    assert attrs["mcp.meta_protocol_version_present"] is True
    assert attrs["mcp.protocol_version_header"] == PROTOCOL_VERSION
    assert "mcp.error.code" not in attrs


def test_notification_stamps_method(otel_spans: InMemorySpanExporter) -> None:
    response = _bare_post(
        "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert response.status_code == 202

    attrs = _request_span(otel_spans).attributes
    assert attrs["mcp.method"] == "notifications/initialized"
    # Acknowledged before classification, so no revision was decided.
    assert "mcp.revision" not in attrs


def test_classic_with_extra_headers_stamps_them(
    otel_spans: InMemorySpanExporter, mcp_log: _ListHandler
) -> None:
    # claude.ai's connector shape: no `_meta`, the negotiated classic
    # version header, plus an extra `Mcp-Method` header. Served classically
    # (test_classic.py owns that contract) — here we pin that the span still
    # records the header facts, because revision-vs-headers is exactly what
    # a "why was this client rejected?" investigation reads first.
    response = _bare_post(
        "/mcp",
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers={
            "MCP-Protocol-Version": "2025-11-25",
            "Mcp-Method": "tools/list",
        },
    )
    assert response.status_code == 200

    attrs = _request_span(otel_spans).attributes
    assert attrs["mcp.method"] == "tools/list"
    assert attrs["mcp.revision"] == "classic"
    assert attrs["mcp.method_header_present"] is True
    assert attrs["mcp.protocol_version_header"] == "2025-11-25"
    assert "mcp.error.code" not in attrs
    assert not _rejects(mcp_log)


def test_modern_ladder_reject_is_observable(
    otel_spans: InMemorySpanExporter, mcp_log: _ListHandler, mcp_post_raw
) -> None:
    # A request that does declare the modern `_meta` still walks the ladder,
    # and a rung failure lands on the span and in the log.
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

    attrs = _request_span(otel_spans).attributes
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


def test_classic_error_reply_is_observable(
    otel_spans: InMemorySpanExporter, mcp_log: _ListHandler
) -> None:
    # Classic errors ride HTTP 200, so span + log are the only server-side
    # trace of them at all.
    response = _bare_post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})
    assert response.status_code == 200
    assert response.json()["error"]["code"] == METHOD_NOT_FOUND

    attrs = _request_span(otel_spans).attributes
    assert attrs["mcp.revision"] == "classic"
    assert attrs["mcp.error.code"] == METHOD_NOT_FOUND

    (record,) = _rejects(mcp_log)
    assert record["error_code"] == METHOD_NOT_FOUND
    assert record["method"] == "prompts/list"


def test_internal_error_is_stamped_but_not_relogged(
    otel_spans: InMemorySpanExporter, mcp_log: _ListHandler, mcp_post
) -> None:
    # -32603 already logs with a traceback in `handle_message` — the reject
    # log stays quiet so the failure isn't reported twice.
    response = mcp_post("/rpc-boom", "boom")
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32603

    attrs = _request_span(otel_spans, path="/rpc-boom").attributes
    assert attrs["mcp.error.code"] == -32603
    assert not _rejects(mcp_log)
