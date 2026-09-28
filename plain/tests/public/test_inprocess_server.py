"""`InProcessServer` handles a request on the calling thread and reports
what a client would have received."""

import asyncio
import socket
from collections.abc import Generator
from contextlib import contextmanager

from inprocess_routers import caller_value, view_value
from plain.http import Request, Response
from plain.server.inprocess import HandledRequest, InProcessServer, SentResponse
from plain.test import case, cases, override_settings, raises
from plain.urls.resolvers import _get_cached_resolver


@contextmanager
def in_process_router() -> Generator[None]:
    try:
        with override_settings(
            URLS_ROUTER="inprocess_routers.InProcessRouter", URLS_TRAILING_SLASH=False
        ):
            _get_cached_resolver.cache_clear()
            yield
    finally:
        _get_cached_resolver.cache_clear()


def get(path: str, *, method: str = "GET") -> Request:
    return Request(
        method=method,
        path=path,
        headers={"Host": "testserver"},
        server_scheme="https",
        server_name="testserver",
        server_port="443",
        remote_addr="127.0.0.1",
    )


def test_send_reports_what_was_sent():
    request = get("/")

    handled = InProcessServer().handle(request)
    assert isinstance(handled, HandledRequest)
    assert isinstance(handled.response, Response)
    assert handled.request is request

    sent = handled.send()
    assert isinstance(sent, SentResponse)
    assert sent.status_code == 200
    assert sent.body == b"Hello, world!"
    assert sent.response is handled.response
    assert sent.request is request


def test_a_head_request_sends_no_body():
    sent = InProcessServer().handle(get("/", method="HEAD")).send()

    assert sent.status_code == 200
    assert sent.body == b""


def test_a_streaming_body_is_read_to_its_end():
    sent = InProcessServer().handle(get("/stream-generator")).send()

    assert sent.body == b"line 1\nline 2\n"
    assert sent.response.streaming


def test_a_body_that_fails_before_its_first_chunk_sends_a_500():
    sent = InProcessServer().handle(get("/stream-fails-first")).send()

    assert sent.status_code == 500
    assert sent.body == b""
    # The view returned a 200. What went out is what `status_code` reports.
    assert sent.response.status_code == 200
    assert isinstance(sent.response.exception, ValueError)


def test_an_exception_in_the_view_becomes_the_error_response():
    with in_process_router():
        sent = InProcessServer().handle(get("/raises")).send()

    assert sent.status_code == 500
    assert isinstance(sent.response.exception, RuntimeError)


def test_an_async_view_is_awaited():
    with in_process_router():
        sent = InProcessServer().handle(get("/async")).send()

    assert sent.status_code == 200
    assert sent.body == b"from an async view"


def test_an_exception_in_an_async_view_becomes_the_error_response():
    with in_process_router():
        sent = InProcessServer().handle(get("/async-raises")).send()

    assert sent.status_code == 500
    assert isinstance(sent.response.exception, RuntimeError)


def test_an_async_streaming_body_is_read_to_its_end():
    with in_process_router():
        sent = InProcessServer().handle(get("/async-stream")).send()

    assert sent.body == b"one two"


def test_a_204_loses_its_content_length():
    with in_process_router():
        sent = InProcessServer().handle(get("/no-content")).send()

    assert sent.status_code == 204
    assert "Content-Length" not in sent.response.headers


def test_a_304_keeps_its_content_length():
    # It describes the body a GET would have had.
    with in_process_router():
        sent = InProcessServer().handle(get("/not-modified")).send()

    assert sent.status_code == 304
    assert sent.response.headers["Content-Length"] == "11"


def test_the_view_runs_in_the_callers_context():
    token = caller_value.set("set by the caller")
    try:
        with in_process_router():
            sent = InProcessServer().handle(get("/caller-value")).send()
    finally:
        caller_value.reset(token)

    assert sent.body == b"set by the caller"


def test_the_body_runs_in_the_callers_context():
    token = caller_value.set("set by the caller")
    try:
        with in_process_router():
            handled = InProcessServer().handle(get("/caller-value-stream"))
    finally:
        caller_value.reset(token)

    # Read after the caller's value is gone: the body runs in the context
    # the pipeline ran in, not the one `send()` is called from.
    assert handled.send().body == b"set by the caller"


@cases(
    case("/sets-view-value", b"set by the view", id="sync view"),
    case("/async-sets-view-value", b"set by the async view", id="async view"),
)
def test_what_the_view_sets_is_seen_by_the_rest_of_its_request(path, expected):
    # One context for the whole request, as under a server: after-middleware
    # and the body both run after the view, and both see what it set.
    with (
        in_process_router(),
        override_settings(MIDDLEWARE=["inprocess_routers.ViewValueMiddleware"]),
    ):
        sent = InProcessServer().handle(get(path)).send()

    assert sent.response.headers["X-View-Value"] == expected.decode()
    assert sent.body == expected


def test_what_the_view_sets_stays_in_its_request():
    with in_process_router():
        InProcessServer().handle(get("/sets-view-value")).send()

    assert view_value.get() == "unset"


def test_a_sync_view_can_be_requested_from_inside_an_event_loop():
    async def request_from_a_coroutine() -> SentResponse:
        return InProcessServer().handle(get("/")).send()

    sent = asyncio.run(request_from_a_coroutine())

    assert sent.body == b"Hello, world!"


def test_middleware_is_loaded_at_the_first_request():
    server = InProcessServer()

    with (
        override_settings(MIDDLEWARE=["inprocess_routers.NoSuchMiddleware"]),
        raises(ImportError),
    ):
        server.handle(get("/"))

    # Nothing was kept from the failed load, so the next request loads it
    # from the settings as they are now.
    assert server.handle(get("/")).send().status_code == 200


def test_a_handled_request_is_sent_once():
    handled = InProcessServer().handle(get("/"))
    handled.send()

    with raises(RuntimeError, match=r"already finished by send\(\)"):
        handled.send()


def test_serve_websocket_refuses_a_response_that_is_not_a_websocket():
    handled = InProcessServer().handle(get("/"))
    server_sock, client_sock = socket.socketpair()

    try:
        with raises(TypeError, match="didn't accept a websocket"):
            asyncio.run(handled.serve_websocket(server_sock))
    finally:
        server_sock.close()
        client_sock.close()

    # Refusing didn't use the request up.
    assert handled.send().status_code == 200
