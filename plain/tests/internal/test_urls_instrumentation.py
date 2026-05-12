"""Pin what path-related instrumentation currently records.

Internal because these tests pin the *value* of the path stored on OTel
spans and exception logs — implementation surface that step #3 of the
URL routing arc will change.

Both observability reads use `request.path`:
- OTel `url.path` span attribute (see `plain/internal/handlers/base.py:126`)
- Exception log `path` field (see `plain/logs/exceptions.py:49` and
  `internal/handlers/exception.py:64`)

Step #3 normalizes the path *before* anything else runs, so `request.path`
becomes the canonical normalized form and a new `request.raw_path` carries
the original for forensics.
"""

from __future__ import annotations

import pytest
from opentelemetry.semconv.attributes import url_attributes

from plain.runtime import settings
from plain.test import Client
from plain.test.otel import install_test_tracer
from plain.urls.resolvers import _get_cached_resolver

_span_exporter = install_test_tracer()


@pytest.fixture
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


def test_otel_url_path_records_request_path(app_router):
    """`GET /` → `url.path` span attribute is `/` (request.path)."""
    Client().get("/")
    span = _request_span(app_router)
    assert span.attributes[url_attributes.URL_PATH] == "/"


def test_otel_url_path_is_unnormalized(app_router):
    """`GET ///` → `url.path` records what arrives at the resolver layer.

    Today: the request layer collapses multiple leading slashes to one, so
    the span sees `/`. Step #3 will normalize explicitly inside the framework
    and the recorded value reflects that — same final value, different
    provenance.
    """
    Client().get("///")
    span = _request_span(app_router)
    assert span.attributes[url_attributes.URL_PATH] == "/"


def test_request_path_and_path_info_are_equal_today():
    """For typical requests (no SCRIPT_NAME), `request.path` and `request.path_info`
    are the same value.

    Step #3 changes this relationship: `request.path` becomes the normalized
    canonical path (what middleware/views/logs should use), and a new
    `request.raw_path` holds the original. Pinning the invariant today makes
    that flip visible.
    """
    from plain.test import RequestFactory

    factory = RequestFactory()
    for path in ["/", "/users/", "/admin/users/42/", "/a/b/c"]:
        request = factory.get(path)
        assert request.path == request.path_info, (
            f"Expected request.path == request.path_info for {path!r}, "
            f"got {request.path!r} vs {request.path_info!r}"
        )


def test_csrf_middleware_reads_path_info():
    """`CsrfViewMiddleware` matches `CSRF_EXEMPT_PATHS` against `request.path_info`.

    Pinned at `plain/csrf/middleware.py:44`. Step #3 may switch path-based
    middleware to read `request.path` (the normalized form). If that happens,
    this test fails loudly — at which point CSRF exempt-pattern semantics
    have shifted under double-slash / dot-segment requests.
    """
    import inspect

    from plain.csrf.middleware import CsrfViewMiddleware

    source = inspect.getsource(CsrfViewMiddleware.should_allow_request)
    assert "request.path_info" in source
    assert "request.path " not in source  # the bare attribute, not path_info


def test_exception_log_records_request_path(error_client):
    """Exception log `path` field uses `request.path`, same source as the OTel
    span attribute (per the divergence fix that unified both).

    Step #3 will redefine `request.path` as the normalized canonical path
    (and add `request.raw_path` for the original); both observability sites
    automatically pick up the new value because they already share a source.

    Attach the capture handler to the framework's module-cached logger
    instance (`plain.logs.exceptions.request_logger`) rather than fetching
    via `logging.getLogger`, since other tests may have evicted that name
    from the logger registry.
    """
    import logging

    from plain.logs.exceptions import request_logger

    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.ERROR)
    request_logger.addHandler(handler)
    try:
        error_client.get("/plain-500/")
    finally:
        request_logger.removeHandler(handler)

    server_errors = [r for r in records if r.message == "Server error"]
    assert server_errors, "Expected a 'Server error' log record from plain.request"
    assert getattr(server_errors[-1], "path") == "/plain-500/"
