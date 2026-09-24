import asyncio
import concurrent.futures
import logging

import pytest
from opentelemetry import trace
from plain.internal.handlers.base import BaseHandler
from plain.internal.handlers.response_lifecycle import ResponseBodyError
from plain.runtime import settings
from plain.test import Client, RequestFactory
from plain.test.otel import install_test_tracer
from plain.urls.resolvers import _get_cached_resolver
from server_stubs import capture_logger

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
    # status=ERROR + error.type is the canonical failure signal. The exception
    # event itself is recorded but we don't branch on exception.escaped —
    # deprecated upstream and unreliable in the Python SDK.
    exception_events = [e for e in span.events if e.name == "exception"]
    assert exception_events


def _invoke_handler(router_path: str) -> None:
    """Run a request through `BaseHandler.handle` with a real thread executor,
    then send its body the way the server does.

    Mirrors the production pipeline (sync hop + asyncio task + sync hop),
    unlike `Client` which short-circuits the executor for sync views.
    """
    _span_exporter.clear()
    original_router = settings.URLS_ROUTER
    settings.URLS_ROUTER = router_path
    _get_cached_resolver.cache_clear()
    try:
        handler = BaseHandler()
        handler.load_middleware()
        request = RequestFactory().get("/")

        async def run():
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                lifecycle = await handler.handle(request, executor)

                async def write() -> None:
                    # Plays the writer: headers go out with the first chunk,
                    # so a lifecycle failing before one is answered with a 500.
                    sent_a_chunk = False
                    try:
                        async for _ in lifecycle:
                            sent_a_chunk = True
                    except ResponseBodyError:
                        if not sent_a_chunk:
                            lifecycle.sent_status_code = 500
                        raise

                try:
                    await lifecycle.send(write)
                except ResponseBodyError:
                    pass  # recorded on the span; what the tests check
                return lifecycle.response

        response = asyncio.run(run())
        assert response.status_code == 200
    finally:
        settings.URLS_ROUTER = original_router
        _get_cached_resolver.cache_clear()


def _assert_child_span_parented_to_server_span() -> None:
    server_span = _server_span()
    child_spans = [
        s for s in _span_exporter.get_finished_spans() if s.name == "view-child-span"
    ]
    assert child_spans, "expected child span from view"
    assert child_spans[0].parent is not None
    assert child_spans[0].parent.span_id == server_span.context.span_id


def test_sync_view_child_span_is_parented_to_server_span() -> None:
    # The sync pipeline runs in a worker thread via `loop.run_in_executor`.
    # `request_ctx` carries the OTel context so a span opened in the view
    # nests under the SERVER span instead of becoming a root span.
    _invoke_handler("middleware_helpers.SyncSpanRouter")
    _assert_child_span_parented_to_server_span()


def test_async_view_child_span_is_parented_to_server_span() -> None:
    # Async views drive the coroutine on an asyncio task bound to
    # `request_ctx`; the SERVER span must still be active inside the awaited
    # body across that task hop.
    _invoke_handler("middleware_helpers.AsyncSpanRouter")
    _assert_child_span_parented_to_server_span()


def _assert_body_spans_nest_under_the_server_span() -> None:
    server_span = _server_span()
    body_spans = [
        s for s in _span_exporter.get_finished_spans() if s.name == "body-child-span"
    ]
    assert len(body_spans) == 2
    for body_span in body_spans:
        assert body_span.parent is not None
        assert body_span.parent.span_id == server_span.context.span_id
        # The request's span covers sending the body.
        assert server_span.end_time >= body_span.end_time


def test_sync_stream_spans_nest_under_the_server_span() -> None:
    _invoke_handler("middleware_helpers.SyncStreamSpanRouter")
    _assert_body_spans_nest_under_the_server_span()


def test_async_stream_spans_nest_under_the_server_span() -> None:
    _invoke_handler("middleware_helpers.AsyncStreamSpanRouter")
    _assert_body_spans_nest_under_the_server_span()


def test_body_error_is_recorded_on_the_server_span() -> None:
    # The status went out as a 200, but the request failed — the entry span
    # is where error attribution looks.
    _invoke_handler("middleware_helpers.StreamFailsRouter")

    span = _server_span()
    assert span.status.status_code == trace.StatusCode.ERROR
    assert span.attributes["http.response.status_code"] == 200
    assert "ValueError" in span.attributes["error.type"]
    assert any(event.name == "exception" for event in span.events)


def test_body_error_log_carries_the_request_span() -> None:
    # Logged inside the request context, so the exported record links to
    # the request's trace instead of becoming an unattached issue.
    with capture_logger("plain.request", level=logging.ERROR) as captured:
        _invoke_handler("middleware_helpers.StreamFailsRouter")

    span = _server_span()
    span_ids = [record.captured_span_id for record in captured.records]  # ty: ignore[unresolved-attribute]
    assert span_ids == [span.context.span_id]


def test_body_failing_before_headers_records_the_500_it_sent() -> None:
    # The writer answers with a 500, not the view's 200 — the span and the
    # duration metric record what went out.
    _invoke_handler("middleware_helpers.StreamFailsFirstRouter")

    span = _server_span()
    assert span.attributes["http.response.status_code"] == 500
    assert span.status.status_code == trace.StatusCode.ERROR
