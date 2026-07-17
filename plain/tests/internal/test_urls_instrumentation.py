"""Pin what path-related instrumentation currently records.

Internal because these tests pin the *value* of the path stored on OTel
spans and exception logs — implementation surface that step #3 of the
URL routing arc will change.

`request.path` is the single source of truth for the URL path: routing,
middleware (CSRF, trailing-slash redirect), the OTel `url.path` span
attribute (`plain/internal/handlers/base.py:126`), and the exception log
`path` field (`plain/logs/exceptions.py:49`,
`internal/handlers/exception.py:64`) all read from it.

Step #3 normalizes the path *before* anything else runs, so `request.path`
becomes the canonical normalized form (and a `request.raw_path` carries
the original for forensics). Both observability sites pick up the new
value automatically because they already share a source.
"""

from __future__ import annotations

from contextlib import contextmanager

from clients import error_client
from opentelemetry.semconv.attributes import url_attributes

from plain.runtime import settings
from plain.test import Client
from plain.test.otel import install_test_tracer
from plain.urls.resolvers import _get_cached_resolver

_span_exporter = install_test_tracer()


@contextmanager
def app_router():
    """Stand up the default app router and drain spans before the test runs."""
    original = settings.URLS_ROUTER
    settings.URLS_ROUTER = "app.urls.AppRouter"
    _get_cached_resolver.cache_clear()
    _span_exporter.clear()
    try:
        yield _span_exporter
    finally:
        settings.URLS_ROUTER = original
        _get_cached_resolver.cache_clear()


def _request_span(spans):
    """Return the SERVER span that carries `url.path`."""
    for span in spans.get_finished_spans():
        if url_attributes.URL_PATH in span.attributes:
            return span
    raise AssertionError("No span with url.path attribute found")


def test_otel_url_path_records_request_path():
    """`GET /` → `url.path` span attribute is `/` (request.path)."""
    with app_router() as spans:
        Client().get("/")
        span = _request_span(spans)
        assert span.attributes[url_attributes.URL_PATH] == "/"


def test_otel_url_path_is_unnormalized():
    """`GET ///` → `url.path` records what arrives at the resolver layer.

    Today: the request layer collapses multiple leading slashes to one, so
    the span sees `/`. Step #3 will normalize explicitly inside the framework
    and the recorded value reflects that — same final value, different
    provenance.
    """
    with app_router() as spans:
        Client().get("///")
        span = _request_span(spans)
        assert span.attributes[url_attributes.URL_PATH] == "/"


def test_exception_log_records_request_path():
    """Exception log `path` field uses `request.path`, same source as the OTel
    span attribute (per the divergence fix that unified both).

    Step #3 will redefine `request.path` as the normalized canonical path
    (and add `request.raw_path` for the original); both observability sites
    automatically pick up the new value because they already share a source.

    Attach via the canonical `logging.getLogger("plain.request")` lookup —
    the framework fetches its logger the same way each request, so any
    handler attached here reliably catches its records.
    """
    import logging

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.ERROR)
    request_logger = logging.getLogger("plain.request")
    request_logger.addHandler(handler)
    try:
        with error_client() as client:
            client.get("/plain-500/")
    finally:
        request_logger.removeHandler(handler)

    server_errors = [r for r in records if r.getMessage() == "Server error"]
    assert server_errors, "Expected a 'Server error' log record from plain.request"
    assert getattr(server_errors[-1], "path") == "/plain-500/"
