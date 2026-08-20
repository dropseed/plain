"""Shared stand-ins for driving server Worker code directly in tests.

Used by the test_server_* internal tests, which construct a real Worker
without a listener, signals, or init_process(), and drive
h1.handle_connection over a socketpair with H1Client/h1_connect.
"""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import h2.config
import h2.connection
import h2.events
import h2.exceptions
from plain.http import ContentTooLargeError413, Response
from plain.runtime import settings
from plain.server.connection import Connection
from plain.server.http import h1
from plain.server.http.h2 import async_handle_h2_connection
from plain.server.http.sink import BodyBudget
from plain.server.workers.worker import Worker


class StubApp:
    """Minimal stand-in for ServerApplication."""

    is_ssl = False
    certfile = None
    keyfile = None
    threads = 1
    reload = False


class StubHeartbeat:
    """Minimal stand-in for WorkerHeartbeat."""

    def __init__(self, *, deadline: float = 0.0) -> None:
        self.deadline = deadline

    def notify(self) -> None:
        pass

    def is_retiring(self) -> bool:
        return False

    def kill_deadline(self) -> float:
        return self.deadline


def make_worker(
    *,
    sockets: list[Any] | None = None,
    heartbeat: StubHeartbeat | None = None,
    handler: Any = None,
) -> Worker:
    worker = Worker(
        age=0,
        ppid=os.getppid(),
        sockets=sockets or [],
        app=StubApp(),  # ty: ignore[invalid-argument-type]
        timeout=5,
        heartbeat=heartbeat or StubHeartbeat(),  # ty: ignore[invalid-argument-type]
        handler=handler,
    )
    # Normally created in init_process(), which these tests bypass.
    worker.tpool = ThreadPoolExecutor(max_workers=1)
    return worker


class H1Client:
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

    async def read_headers(self) -> bytes:
        """Read exactly one response header block (through the blank line).

        This is how a client reads a bodiless response (HEAD, 1xx, 204,
        304) — even one carrying a Content-Length, which describes the
        body a GET would have had, not bytes that follow.
        """
        return await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), timeout=5)

    async def read_response(self) -> tuple[bytes, bytes]:
        """Read one response; return (headers, body) split at the blank line."""
        reader = self.reader
        header_blob = await self.read_headers()

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


async def h1_connect(worker: Worker) -> H1Client:
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
    return H1Client(client_reader, client_writer, conn, server_task, worker)


def chunked_payload(data: bytes, chunk_size: int, trailer: bytes = b"") -> bytes:
    """Frame data as a chunked transfer-encoded body.

    A trailer is one or more complete header lines WITHOUT the final
    blank line — the terminating CRLF CRLF is added here (RFC 9112 §7.1.2).
    """
    parts = []
    for start in range(0, len(data), chunk_size):
        piece = data[start : start + chunk_size]
        parts.append(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
    if trailer:
        parts.append(b"0\r\n" + trailer + b"\r\n\r\n")
    else:
        parts.append(b"0\r\n\r\n")
    return b"".join(parts)


def length_request(body: bytes) -> bytes:
    """Raw h1 POST with a declared Content-Length body."""
    return (
        b"POST / HTTP/1.1\r\nHost: testserver\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )


def chunked_request(body: bytes, chunk_size: int) -> bytes:
    """Raw h1 POST with a chunked transfer-encoded body."""
    return (
        b"POST / HTTP/1.1\r\nHost: testserver\r\nTransfer-Encoding: chunked\r\n\r\n"
    ) + chunked_payload(body, chunk_size)


async def h1_roundtrip(worker: Worker, request: bytes) -> tuple[bytes, bytes]:
    """Send one raw h1 request through handle_connection; return (headers, body)."""
    client = await h1_connect(worker)
    try:
        await client.send(request)
        return await client.read_response()
    finally:
        client.teardown()


class ResponseHandler:
    """Handler stub that builds a fresh response per request."""

    def __init__(self, make_response: Callable[[], Response]) -> None:
        self.make_response = make_response

    async def handle(self, request: Any, executor: Any) -> Response:
        return self.make_response()


class BodyLengthHandler:
    """Handler that reads request.body in the thread pool and returns its
    length — mirroring how production sync views read bodies. Maps the
    app-layer body-size exception (DATA_UPLOAD_MAX_MEMORY_SIZE) to a 413
    the way the production handler maps any HTTPException.
    """

    async def handle(self, request: Any, executor: Any) -> Response:
        loop = asyncio.get_running_loop()

        def read_body() -> Response:
            try:
                body = request.body
            except ContentTooLargeError413:
                return Response(b"too large", status_code=413)
            return Response(str(len(body)).encode(), content_type="text/plain")

        return await loop.run_in_executor(executor, read_body)


class H2Client:
    """Client half of an h2 connection: real h2 state machine over streams."""

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.conn = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=True)
        )
        self.events: list[h2.events.Event] = []
        self.eof = False

    async def flush(self) -> None:
        data = self.conn.data_to_send()
        if data:
            self.writer.write(data)
            await self.writer.drain()

    async def start(self) -> None:
        self.conn.initiate_connection()
        await self.flush()

    async def request(
        self,
        stream_id: int,
        path: str = "/",
        *,
        method: str | None = None,
        body_frames: list[bytes] | None = None,
        content_length: int | None = None,
        end_stream: bool = True,
    ) -> None:
        """Send a request; body_frames stream as DATA frames if given.

        end_stream=False leaves the request body open (an in-flight
        upload) after the last frame.
        """
        headers = [
            (":method", method or ("POST" if body_frames else "GET")),
            (":path", path),
            (":scheme", "http"),
            (":authority", "testserver"),
        ]
        if content_length is not None:
            headers.append(("content-length", str(content_length)))
        frames = body_frames or []
        self.conn.send_headers(stream_id, headers, end_stream=not frames and end_stream)
        await self.flush()
        for i, frame in enumerate(frames):
            try:
                self.conn.send_data(
                    stream_id,
                    frame,
                    end_stream=end_stream and i == len(frames) - 1,
                )
            except h2.exceptions.ProtocolError:
                # Stream already closed by a server-side rejection.
                break
            await self.flush()

    async def response_headers(
        self, stream_id: int, *, timeout: float = 5.0
    ) -> dict[bytes, bytes]:
        """Wait for the response headers on a stream; return them as a dict."""
        event = await self.wait_for(
            lambda e: (
                isinstance(e, h2.events.ResponseReceived) and e.stream_id == stream_id
            ),
            timeout=timeout,
        )
        assert isinstance(event, h2.events.ResponseReceived)
        return dict(event.headers or [])

    async def response_status(self, stream_id: int, *, timeout: float = 5.0) -> str:
        """Wait for the response headers on a stream; return its :status."""
        headers = await self.response_headers(stream_id, timeout=timeout)
        status = headers.get(b":status")
        if status is None:
            raise AssertionError(f"response without :status: {headers}")
        return status.decode()

    async def wait_for(
        self, predicate: Any, *, timeout: float = 5.0
    ) -> h2.events.Event:
        """Read frames until an event matching predicate arrives."""
        for event in self.events:
            if predicate(event):
                return event
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            assert remaining > 0, f"timed out waiting; saw {self.events}"
            data = await asyncio.wait_for(self.reader.read(65535), timeout=remaining)
            if not data:
                self.eof = True
                raise AssertionError(f"connection closed; saw {self.events}")
            new = self.conn.receive_data(data)
            self.events.extend(new)
            await self.flush()  # acks (SETTINGS, etc.)
            for event in new:
                if predicate(event):
                    return event

    async def wait_for_eof(self, *, timeout: float = 5.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not self.eof:
            remaining = deadline - asyncio.get_running_loop().time()
            assert remaining > 0, "timed out waiting for connection close"
            data = await asyncio.wait_for(self.reader.read(65535), timeout=remaining)
            if not data:
                self.eof = True
                break
            self.events.extend(self.conn.receive_data(data))


async def h2_connect(
    handler: Any,
    shutdown_event: asyncio.Event,
    keepalive_timeout: float = 300.0,
    *,
    max_request_body: int | None = None,
    max_inflight_body: int | None = None,
    spool_size: int | None = None,
    body_min_rate: int = 0,
    body_budget: BodyBudget | None = None,
) -> tuple[H2Client, asyncio.Task[None], ThreadPoolExecutor]:
    """Start async_handle_h2_connection over a socketpair with a real client."""
    server_sock, client_sock = socket.socketpair()
    server_reader, server_writer = await asyncio.open_connection(sock=server_sock)
    client_reader, client_writer = await asyncio.open_connection(sock=client_sock)

    executor = ThreadPoolExecutor(max_workers=1)
    server_task = asyncio.get_running_loop().create_task(
        async_handle_h2_connection(
            server_reader,
            server_writer,
            ("127.0.0.1", 12345),
            ("127.0.0.1", 80),
            handler,
            False,
            executor,
            shutdown_event=shutdown_event,
            keepalive_timeout=keepalive_timeout,
            # Mirror the Worker's resolution: with no policy cap, the
            # in-flight budget floors any single body.
            max_request_body=(
                max_request_body if max_request_body is not None else max_inflight_body
            ),
            body_budget=(
                body_budget
                if body_budget is not None
                else BodyBudget(max_inflight_body)
            ),
            body_min_rate=body_min_rate,
            spool_size=(
                spool_size
                if spool_size is not None
                else settings.SERVER_BODY_MAX_MEMORY_SIZE
            ),
        )
    )

    client = H2Client(client_reader, client_writer)
    await client.start()
    return client, server_task, executor
