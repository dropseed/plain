from __future__ import annotations

import pytest
from opentelemetry import trace

from plain.test import Client
from plain.test.otel import install_test_tracer

_span_exporter = install_test_tracer()


@pytest.fixture
def _otel_clean() -> None:
    _span_exporter.clear()


def _server_span():
    spans = [
        s
        for s in _span_exporter.get_finished_spans()
        if s.kind == trace.SpanKind.SERVER
    ]
    assert spans, "no SERVER span captured"
    return spans[-1]


@pytest.mark.usefixtures("_otel_clean")
def test_homepage_span_name_and_route_attribute() -> None:
    Client().get("/")

    span = _server_span()
    assert span.name == "GET /"
    assert span.attributes["http.route"] == "/"
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.response.status_code"] == 200


@pytest.mark.usefixtures("_otel_clean")
def test_404_span_name_omits_path() -> None:
    # Per OTel HTTP semconv, unmatched requests must not include the path
    # in the span name — keeps span-name cardinality bounded under scanner
    # traffic on /xmlrpc.php, /wp-login.php, etc.
    Client(raise_request_exception=False).get("/does-not-exist")

    span = _server_span()
    assert span.name == "GET"
    assert "http.route" not in span.attributes
    assert span.attributes["http.response.status_code"] == 404
    assert span.status.status_code == trace.StatusCode.UNSET


@pytest.mark.usefixtures("_otel_clean")
def test_500_records_exception_and_error_status(error_client) -> None:
    error_client.get("/plain-500/")

    span = _server_span()
    assert span.name == "GET /plain-500/"
    assert span.attributes["http.response.status_code"] == 500
    assert span.status.status_code == trace.StatusCode.ERROR
    assert span.attributes["error.type"] == "RuntimeError"
    exception_events = [e for e in span.events if e.name == "exception"]
    assert exception_events
