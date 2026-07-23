"""H2 connections must drain gracefully when worker shutdown starts.

When the worker's shutdown event is set, an HTTP/2 connection should:
refuse newly-opened streams with REFUSED_STREAM (safe for clients to
retry), let already-dispatched streams run to completion, then close the
connection with GOAWAY. An idle connection should close promptly instead
of parking in its 300s idle read until the drain deadline cancels it.

These tests drive async_handle_h2_connection directly over a socketpair
with a real client-side h2 state machine — no TLS, no worker process.
The TLS/ALPN socket-level contract is covered by tools/h2-shutdown-test.
"""

from __future__ import annotations

import asyncio
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import h2.config
import h2.connection
import h2.errors
import h2.events

from plain.http import Response
from plain.server.http.h2 import async_handle_h2_connection


class _Handler:
    """Stand-in for the server handler — responds when released."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.release.set()

    async def handle(self, request: Any, executor: Any) -> Response:
        await self.release.wait()
        return Response(b"ok", content_type="text/plain")


class _H2Client:
    """Client half of the connection: real h2 state machine over streams."""

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

    async def request(self, stream_id: int, path: str = "/") -> None:
        self.conn.send_headers(
            stream_id,
            [
                (":method", "GET"),
                (":path", path),
                (":scheme", "http"),
                (":authority", "testserver"),
            ],
            end_stream=True,
        )
        await self.flush()

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


async def _connect(
    handler: _Handler, shutdown_event: asyncio.Event
) -> tuple[_H2Client, asyncio.Task[None], ThreadPoolExecutor]:
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
        )
    )

    client = _H2Client(client_reader, client_writer)
    await client.start()
    return client, server_task, executor


def test_idle_h2_connection_closes_promptly_on_shutdown() -> None:
    async def scenario() -> None:
        shutdown_event = asyncio.Event()
        handler = _Handler()
        client, server_task, executor = await _connect(handler, shutdown_event)
        try:
            # Sanity request/response before shutdown.
            await client.request(1)
            await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamEnded) and e.stream_id == 1
            )

            shutdown_event.set()

            # Idle connection closes with GOAWAY well before the 300s
            # idle timeout or any drain deadline.
            await client.wait_for(
                lambda e: isinstance(e, h2.events.ConnectionTerminated),
                timeout=3.0,
            )
            await client.wait_for_eof(timeout=3.0)
            await asyncio.wait_for(server_task, timeout=3.0)
        finally:
            server_task.cancel()
            executor.shutdown(wait=False)

    asyncio.run(scenario())


def test_mid_upload_stream_survives_drain() -> None:
    # A stream whose HEADERS arrived before shutdown but whose body is
    # still uploading must be drained, not abandoned — GOAWAY's
    # last_stream_id covers it, so the client would treat an abandoned
    # stream as possibly-processed and never retry it.
    async def scenario() -> None:
        shutdown_event = asyncio.Event()
        handler = _Handler()
        client, server_task, executor = await _connect(handler, shutdown_event)
        try:
            body = b"x" * 64
            client.conn.send_headers(
                1,
                [
                    (":method", "POST"),
                    (":path", "/"),
                    (":scheme", "http"),
                    (":authority", "testserver"),
                    ("content-length", str(len(body))),
                ],
            )
            await client.flush()
            await asyncio.sleep(0.1)  # server has HEADERS, no body yet

            shutdown_event.set()
            await asyncio.sleep(0.7)  # past a drain poll — must stay open

            client.conn.send_data(1, body, end_stream=True)
            await client.flush()

            response = await client.wait_for(
                lambda e: isinstance(e, h2.events.ResponseReceived) and e.stream_id == 1
            )
            assert isinstance(response, h2.events.ResponseReceived)
            assert dict(response.headers or [])[b":status"] == b"200"

            await client.wait_for(
                lambda e: isinstance(e, h2.events.ConnectionTerminated),
                timeout=3.0,
            )
            await asyncio.wait_for(server_task, timeout=3.0)
        finally:
            server_task.cancel()
            executor.shutdown(wait=False)

    asyncio.run(scenario())


def test_draining_refuses_new_streams_and_completes_inflight() -> None:
    async def scenario() -> None:
        shutdown_event = asyncio.Event()
        handler = _Handler()
        handler.release.clear()  # hold the in-flight stream open
        client, server_task, executor = await _connect(handler, shutdown_event)
        try:
            # Stream 1 dispatches and blocks in the handler.
            await client.request(1)
            await asyncio.sleep(0.1)  # let the server dispatch it

            shutdown_event.set()
            await asyncio.sleep(0.1)  # let the server notice

            # A stream opened during the drain is refused, not processed.
            await client.request(3)
            reset = await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamReset) and e.stream_id == 3
            )
            assert isinstance(reset, h2.events.StreamReset)
            assert reset.error_code == h2.errors.ErrorCodes.REFUSED_STREAM

            # The in-flight stream still completes normally.
            handler.release.set()
            response = await client.wait_for(
                lambda e: isinstance(e, h2.events.ResponseReceived) and e.stream_id == 1
            )
            assert isinstance(response, h2.events.ResponseReceived)
            status = dict(response.headers or [])[b":status"]
            assert status == b"200"
            await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamEnded) and e.stream_id == 1
            )

            # Then the connection closes out with GOAWAY.
            await client.wait_for(
                lambda e: isinstance(e, h2.events.ConnectionTerminated),
                timeout=3.0,
            )
            await asyncio.wait_for(server_task, timeout=3.0)
        finally:
            server_task.cancel()
            executor.shutdown(wait=False)

    asyncio.run(scenario())
