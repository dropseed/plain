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
from server_stubs import StubApp, make_worker

from plain.http import Response
from plain.server.connection import Connection
from plain.server.http import h1
from plain.server.http.unreader import AsyncBridgeUnreader
from plain.server.workers.worker import Worker


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


class _Client:
    """Client half of the socketpair plus the running server task."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        conn: Connection,
        server_task: asyncio.Task[None],
        worker: Worker,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.conn = conn
        self.server_task = server_task
        self.worker = worker

    async def send(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def read_response(self) -> tuple[bytes, bytes]:
        """Read one response; return (headers, body) split at the blank line."""
        reader = self.reader
        header_blob = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)

        if b"transfer-encoding: chunked" in header_blob.lower():
            body = b""
            while True:
                size_line = await asyncio.wait_for(reader.readuntil(b"\r\n"), timeout=5)
                size = int(size_line.strip().split(b";")[0], 16)
                chunk = await asyncio.wait_for(reader.readexactly(size + 2), timeout=5)
                if size == 0:
                    break
                body += chunk[:-2]
            return header_blob, body

        content_length = 0
        for line in header_blob.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                content_length = int(line.split(b":", 1)[1])
        body = await asyncio.wait_for(reader.readexactly(content_length), timeout=5)
        return header_blob, body

    async def assert_closed(self) -> None:
        """The keepalive loop exited and wrote nothing further.

        The socket close itself is _on_connection's job, so mimic it here.
        "Closed" reads as a clean EOF, or as a reset when the server closed
        with an unread request still in the socket (Linux RSTs there where
        macOS sends FIN) — both mean the connection is gone. An extra
        *response* would instead surface as non-empty read bytes.
        """
        await asyncio.wait_for(self.server_task, timeout=5)
        self.conn.close()
        try:
            assert await asyncio.wait_for(self.reader.read(1), timeout=5) == b""
        except ConnectionResetError:
            pass

    def teardown(self) -> None:
        self.server_task.cancel()
        self.conn.close()
        self.writer.close()
        self.worker.tpool.shutdown(wait=False)


async def _connect(worker: Worker) -> _Client:
    server_sock, client_sock = socket.socketpair()
    server_reader, server_writer = await asyncio.open_connection(sock=server_sock)
    client_reader, client_writer = await asyncio.open_connection(sock=client_sock)

    conn = Connection(
        worker.app,
        server_reader,
        server_writer,
        ("127.0.0.1", 12345),
        ("127.0.0.1", 80),
    )
    server_task = asyncio.get_running_loop().create_task(
        h1.handle_connection(worker, conn)
    )
    return _Client(client_reader, client_writer, conn, server_task, worker)


def test_request_arriving_after_shutdown_starts_is_served_with_close() -> None:
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
            # start shutdown — what Worker._signal_exit does on SIGTERM.
            await asyncio.sleep(0.05)
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
    # A known-length body (pre-buffer path) is read and the connection
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
    # A chunked body within max_body is pre-buffered and framed by the
    # parser's ChunkedReader; the connection stays alive afterward.
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


def test_bridge_body_read_respects_drain_deadline() -> None:
    # During shutdown drain, large-body (bridge) reads are capped by the
    # same absolute deadline as pre-buffered reads — a stalled client
    # can't hold the read open for a fresh worker.timeout per chunk.
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        worker = make_worker(handler=_Handler())
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
            worker.alive = False
            worker.drain_read_deadline = time.monotonic() + 0.2
            unreader = AsyncBridgeUnreader(b"", conn, loop, timeout=30, worker=worker)
            # The client sends nothing — the read must give up at the
            # deadline, not after the 30s per-chunk timeout.
            start = time.monotonic()
            with pytest.raises(TimeoutError):
                await loop.run_in_executor(None, unreader.chunk)
            assert time.monotonic() - start < 2
        finally:
            client_writer.close()
            server_writer.close()
            worker.tpool.shutdown(wait=False)

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
