"""Shared stand-ins for driving server Worker code directly in tests.

Used by the test_server_* internal tests, which construct a real Worker
without a listener, signals, or init_process(), and drive
h1.handle_connection over a socketpair with H1Client/h1_connect.
"""

from __future__ import annotations

import asyncio
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from plain.server.connection import Connection
from plain.server.http import h1
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
    """Frame data as a chunked transfer-encoded body."""
    parts = []
    for start in range(0, len(data), chunk_size):
        piece = data[start : start + chunk_size]
        parts.append(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
    parts.append(b"0\r\n" + trailer + b"\r\n")
    return b"".join(parts)
