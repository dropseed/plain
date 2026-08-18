"""H1 keepalive connections must serve, not drop, requests during shutdown.

When shutdown starts (worker.alive flips False), a request that has
already arrived on an established keepalive connection — e.g. a router's
pooled connection to the dyno — must still be read and served with
Connection: close. The old loop gated on worker.alive at the top, so a
request landing during the keepalive wait was left unread and the socket
closed on it: the client saw a dropped request (Heroku router: H13, one
per worker recycle under webhook traffic).

The invariant under test: the loop exits exactly when a response was
framed Connection: close, no matter when shutdown starts — before the
request is read, or mid-dispatch while the view is running.

The idle wait between requests is long (SERVER_KEEPALIVE_TIMEOUT, so the
router is always the side that closes an idle pooled connection), but it
must collapse to a short grace window once shutdown starts — otherwise
every drain pins to the full graceful timeout.

These tests drive h1.handle_connection directly over a socketpair with a
real Worker object — no listener, no signals. The socket-level contract
(SIGTERM, drain, exit code) is covered by tools/shutdown-test.
"""

from __future__ import annotations

import asyncio
import socket
import time
from collections.abc import Callable
from typing import Any

import pytest
from plain.http import Response
from plain.server.connection import Connection
from plain.server.http import h1
from server_stubs import BodyLengthHandler, StubApp, h1_connect, make_worker


class _Handler:
    """Stand-in for the server handler."""

    def __init__(self) -> None:
        self.on_handle: Callable[[], None] | None = None
        self.response_headers: dict[str, str] = {}

    async def handle(self, request: Any, executor: Any) -> Response:
        if self.on_handle is not None:
            self.on_handle()
        response = Response(b"ok", content_type="text/plain")
        for name, value in self.response_headers.items():
            response.headers[name] = value
        return response


_REQUEST = b"GET / HTTP/1.1\r\nHost: testserver\r\n\r\n"
_POST = b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 5\r\n\r\nhello"
_CHUNKED_POST = (
    b"POST / HTTP/1.1\r\nHost: testserver\r\n"
    b"Transfer-Encoding: chunked\r\n\r\n"
    b"5\r\nhello\r\n0\r\n\r\n"
)


# The socketpair harness (H1Client / h1_connect) lives in server_stubs
# and is shared with test_server_upload_integrity.
_connect = h1_connect


@pytest.mark.parametrize(
    "full_drain",
    [
        pytest.param(True, id="begin_drain"),
        pytest.param(False, id="alive_flips_first"),
    ],
)
def test_request_arriving_after_shutdown_starts_is_served_with_close(
    full_drain: bool,
) -> None:
    # full_drain=True is SIGTERM (Worker._begin_drain): the shutdown event
    # collapses the idle wait to a short grace window, and a request
    # already being written onto the pooled connection must land inside
    # it. full_drain=False is the transient reload state — the Reloader
    # thread flips alive before the heartbeat loop runs _begin_drain.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            # First request establishes the keepalive connection.
            await client.send(_REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" not in headers.lower()
            assert body == b"ok"

            # Let the connection settle into the keepalive wait, then
            # start shutdown.
            await asyncio.sleep(0.05)
            if full_drain:
                worker._begin_drain()
            else:
                worker.alive = False

            # A request already on the wire when the worker notices
            # shutdown must be served, not dropped with the socket close.
            await client.send(_REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" in headers.lower()
            assert body == b"ok"

            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_shutdown_during_dispatch_frames_the_response_close() -> None:
    # Shutdown can start while the view is running. The response headers
    # haven't been written yet, so the response must still be framed
    # Connection: close — a keep-alive-framed response followed by a
    # socket close is a dropped request for a client that pipelines or
    # reuses the connection (Heroku router: H13).
    async def scenario() -> None:
        handler = _Handler()
        worker = make_worker(handler=handler)
        handler.on_handle = lambda: setattr(worker, "alive", False)
        client = await _connect(worker)

        try:
            await client.send(_REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" in headers.lower()
            assert body == b"ok"

            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_sequential_keepalive_requests_are_served() -> None:
    # The bread-and-butter path: two requests sent one-after-another on
    # one keepalive connection (not coalesced) are both served inline.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            for _ in range(2):
                await client.send(_REQUEST)
                headers, body = await client.read_response()
                assert b"200" in headers.split(b"\r\n", 1)[0]
                assert b"connection: close" not in headers.lower()
                assert body == b"ok"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_content_length_body_is_served() -> None:
    # A known-length body (held in sink memory) is read and the connection
    # stays alive for the next request.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(_POST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" not in headers.lower()
            assert body == b"ok"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_chunked_body_is_served_and_keepalives() -> None:
    # A chunked body, decoded at ingest by ChunkedDecoder; the
    # connection stays alive afterward.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(_CHUNKED_POST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" not in headers.lower()
            assert body == b"ok"

            # Connection is reusable for a following request.
            await client.send(_REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"ok"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_bodiless_request_with_trailing_crlf_keepalives() -> None:
    # A stray trailing CRLF after a bodiless request (RFC 9112 §2.2
    # tolerance) must not be mistaken for a pipelined request and tear
    # down the keepalive connection.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(_REQUEST + b"\r\n")
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" not in headers.lower()
            assert body == b"ok"

            # Connection is still usable.
            await client.send(_REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"ok"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_pipelined_after_chunked_gets_connection_close() -> None:
    # A request pipelined behind a chunked body must not be silently
    # dropped: the chunked response carries Connection: close and the
    # connection closes so the client retries the second request.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(_CHUNKED_POST + _REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" in headers.lower()
            assert body == b"ok"
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_chunked_complete_with_binary_pipelined_tail_is_framed() -> None:
    # Completion is detected from the parse position, not a CRLFCRLF
    # buffer suffix — a complete chunked body followed by pipelined bytes
    # that don't end in CRLFCRLF is still recognized and served (with
    # close), not mishandled as incomplete.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            # Trailing pipelined bytes that do NOT end in \r\n\r\n.
            await client.send(_CHUNKED_POST + b"GET /2 HTTP/1.1\r\nHost: x")
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" in headers.lower()
            assert body == b"ok"
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_REQUEST + _REQUEST, id="after_bodiless"),
        pytest.param(_POST + _REQUEST, id="after_body"),
    ],
)
def test_pipelined_request_gets_connection_close(payload: bytes) -> None:
    # We deliberately do NOT serve inline-pipelined requests: re-framing
    # the trailing bytes ourselves would make our body-boundary detection
    # a request splitter (a smuggling surface). Instead the first response
    # carries Connection: close and the connection closes, so the client
    # retries the second request on a fresh connection.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(payload)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" in headers.lower()
            assert body == b"ok"
            # The second (pipelined) request is not served.
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_idle_h1_connection_closes_promptly_on_shutdown() -> None:
    # An idle keepalive connection must close within the short shutdown
    # grace window, not park in the long SERVER_KEEPALIVE_TIMEOUT wait —
    # that would pin every drain to the full graceful timeout and end in
    # task cancellation (an RST to the client).
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(_REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"ok"

            # Let the connection settle into the keepalive wait, then
            # start shutdown — what SIGTERM triggers.
            await asyncio.sleep(0.05)
            worker._begin_drain()

            # The grace window is _recv_timeout (~2s early in the drain),
            # so the close lands well under the keepalive timeout and the
            # graceful window, but not instantly. The bound leaves slack
            # for a loaded CI box; what matters is ≪ 300s and ≪ 30s.
            start = time.monotonic()
            await client.assert_closed()
            assert time.monotonic() - start < 4
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_request_within_shutdown_grace_window_is_served() -> None:
    # The grace window after shutdown must stay ~2s wide — production
    # drains rely on it (routers keep writing onto pooled connections
    # throughout the drain). This pins the lower bound so a refactor
    # can't silently shrink it; the test above pins the upper bound.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(_REQUEST)
            headers, _ = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]

            await asyncio.sleep(0.05)
            worker._begin_drain()

            # Well inside the ~2s grace, but past a 0.5s-style window.
            await asyncio.sleep(1.0)

            await client.send(_REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" in headers.lower()
            assert body == b"ok"

            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "requests_before_idle",
    [
        pytest.param(0, id="fresh_connection"),
        pytest.param(1, id="reused_connection"),
    ],
)
def test_request_after_long_idle_is_served_keepalive(
    monkeypatch: pytest.MonkeyPatch, requests_before_idle: int
) -> None:
    # The wait for a request's first byte is SERVER_KEEPALIVE_TIMEOUT,
    # not the per-recv progress timeout — for a fresh pooled connection
    # (the router doesn't distinguish fresh from reused when it writes a
    # request onto the pool) and a reused one alike. A router reusing a
    # connection after a quiet spell must get a normal keep-alive
    # response, not a socket closed out from under its request (Heroku
    # H13/H18). Shrink the per-recv timeout so a regression here fails in
    # a fraction of a second instead of this test sleeping real seconds.
    monkeypatch.setattr(h1, "RECV_PROGRESS_TIMEOUT", 0.2)

    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            for _ in range(requests_before_idle):
                await client.send(_REQUEST)
                headers, _ = await client.read_response()
                assert b"200" in headers.split(b"\r\n", 1)[0]
                assert b"connection: close" not in headers.lower()

            # Much longer than the per-recv progress timeout.
            await asyncio.sleep(0.5)

            await client.send(_REQUEST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" not in headers.lower()
            assert body == b"ok"
        finally:
            client.teardown()

    asyncio.run(scenario())


_BIG_POST = (
    b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 20000\r\n\r\n"
    + b"x" * 20000
)


def test_pipelined_request_after_exactly_consumed_body_is_served() -> None:
    # A large body can be consumed exactly (recv returns precise slices
    # of wait_readable's peeked buffer), leaving a pipelined request
    # buffered with no body over-read to detect. Those bytes ARE the next
    # request — the keepalive wait must notice them instead of blocking
    # on the socket until the idle timeout, which would leave a fully
    # received request unanswered.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(_BIG_POST + _REQUEST)

            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"ok"

            # The pipelined GET is served as the next keepalive request.
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"ok"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_partial_pipelined_request_prefix_is_not_lost() -> None:
    # Bytes of the next request that arrive in the same segment as a
    # fully-consumed body must survive the keepalive wait intact —
    # skipping or overwriting them would desync the request framing.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(_BIG_POST + b"GET / HTTP/1.1\r\nHost: testserv")

            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"ok"

            # Complete the second request; it must parse from the start.
            await client.send(b"er\r\n\r\n")
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert body == b"ok"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_large_body_ingest_reads_peeked_bytes() -> None:
    # Bodies larger than max_body spool through the sink, whose ingest
    # loop must drain bytes peeked by the keepalive wait — reading the
    # socket directly would strand them and stall the body read until it
    # times out. The connection stays reusable: the body was fully
    # consumed at ingest.
    async def scenario() -> None:
        worker = make_worker(handler=BodyLengthHandler())
        worker.body_max_memory_size = 1000  # force the disk spool
        client = await _connect(worker)

        try:
            await client.send(_BIG_POST)
            headers, body = await client.read_response()
            assert b"200" in headers.split(b"\r\n", 1)[0]
            assert b"connection: close" not in headers.lower()
            assert body == b"20000"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_wait_readable_notices_already_peeked_bytes() -> None:
    # Bytes stranded in the peek buffer (a pipelined request behind an
    # exactly-consumed body) ARE the next request — wait_readable must
    # return immediately rather than blocking on the socket. Seeds the
    # buffer directly: whether real traffic strands bytes there depends
    # on kernel segmentation, so the socket-level tests can't pin this.
    async def scenario() -> None:
        server_sock, client_sock = socket.socketpair()
        server_reader, server_writer = await asyncio.open_connection(sock=server_sock)
        _, client_writer = await asyncio.open_connection(sock=client_sock)
        conn = Connection(
            StubApp(),  # ty: ignore[invalid-argument-type]
            server_reader,
            server_writer,
            ("127.0.0.1", 12345),
            ("127.0.0.1", 80),
        )

        try:
            conn._peeked = b"GET / HTTP/1.1\r\n"
            assert await asyncio.wait_for(conn.wait_readable(), timeout=1)
            assert conn._peeked == b"GET / HTTP/1.1\r\n"
        finally:
            client_writer.close()
            server_writer.close()

    asyncio.run(scenario())


def test_idle_keepalive_timeout_expiry_closes_the_connection() -> None:
    # When SERVER_KEEPALIVE_TIMEOUT does expire with no request arriving,
    # the connection closes cleanly.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        worker.keepalive_timeout = 0.2
        client = await _connect(worker)

        try:
            await client.send(_REQUEST)
            await client.read_response()

            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_shutdown_mid_body_read_bounds_the_read() -> None:
    # SIGTERM landing while a request body is mid-read must still bound
    # the read: the drain deadline is consulted live on every recv, not
    # snapshotted when the request started.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\n"
                b"Content-Length: 10\r\n\r\nhello"
            )
            await asyncio.sleep(0.05)  # server is now waiting on body bytes

            # What Worker.run() does when shutdown starts mid-request.
            worker.alive = False
            worker.shutdown_event.set()
            worker.drain_read_deadline = time.monotonic() + 0.3

            headers, _ = await client.read_response()
            assert b"408" in headers.split(b"\r\n", 1)[0]
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_shutdown_mid_chunked_read_bounds_the_read() -> None:
    # Same drain bound as the Content-Length path, for chunked bodies:
    # a chunked upload still trickling past the drain deadline is
    # abandoned with a 408 rather than pinned until task cancellation.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            # Headers + an incomplete chunked body (no terminating 0-chunk).
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n"
                b"5\r\nhello\r\n"
            )
            await asyncio.sleep(0.05)  # server is waiting on more chunks

            worker.alive = False
            worker.shutdown_event.set()
            worker.drain_read_deadline = time.monotonic() + 0.3

            headers, _ = await client.read_response()
            assert b"408" in headers.split(b"\r\n", 1)[0]
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_unsupported_transfer_encoding_is_rejected_by_parser() -> None:
    # A transfer coding the parser doesn't implement has unknown framing,
    # so it can't be read or skipped safely — the parser (set_body_reader,
    # the one framing authority) rejects it with 501 Not Implemented. h1
    # no longer second-guesses this with its own gate.
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\n"
                b"Transfer-Encoding: bogus\r\n\r\n"
            )
            headers, _ = await client.read_response()
            status_line = headers.split(b"\r\n", 1)[0]
            assert b"501" in status_line
            assert b"Not Implemented" in status_line
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_upgrade_response_still_honors_shutdown_close() -> None:
    # An upgrade response frames "Connection: upgrade", but the loop exit
    # must still follow the close decision — otherwise force_close()
    # (shutdown) is silently ignored and the connection keeps serving
    # requests for the whole graceful window.
    async def scenario() -> None:
        handler = _Handler()
        worker = make_worker(handler=handler)
        handler.response_headers = {"Connection": "upgrade"}
        handler.on_handle = lambda: setattr(worker, "alive", False)
        client = await _connect(worker)

        try:
            await client.send(_REQUEST)
            headers, _ = await client.read_response()
            assert b"connection: upgrade" in headers.lower()

            # A follow-up request must not be served.
            await client.send(_REQUEST)
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_pipelined_requests_stop_after_shutdown_response() -> None:
    # During shutdown exactly one pending request is served — the
    # Connection: close response is honored server-side even though the
    # next pipelined request is already buffered, so a client that keeps
    # pipelining doesn't hold the drain open indefinitely. (It knows the
    # second request went unprocessed and can safely retry it.)
    async def scenario() -> None:
        worker = make_worker(handler=_Handler())
        client = await _connect(worker)

        try:
            worker.alive = False
            await client.send(_REQUEST + _REQUEST)

            headers, _ = await client.read_response()
            assert b"connection: close" in headers.lower()

            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(scenario())
