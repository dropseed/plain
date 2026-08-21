"""An unexpected exception anywhere in a connection's handling must be
logged by plain itself, not escape into asyncio's default exception
handler.

The body-abort fix removed the known RuntimeError escape (Sentry
PULLAPPROVE5-7N). The connection-level triage now lives in one place —
Worker._serve_connection — covering ALPN/TLS setup and both protocol
handlers; this pins that layer with an h1 bug as the trigger.
"""

from __future__ import annotations

import asyncio
import logging
import socket

import pytest
from plain.http import Response
from plain.server.connection import Connection
from plain.server.http import h1
from server_stubs import ResponseHandler, make_worker

_GET = b"GET / HTTP/1.1\r\nHost: testserver\r\n\r\n"


def test_unexpected_handler_error_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken_read_headers(worker, conn):
        raise RuntimeError("simulated handler bug")

    monkeypatch.setattr(h1, "async_read_headers", broken_read_headers)

    async def scenario() -> None:
        worker = make_worker(
            handler=ResponseHandler(lambda: Response(b"ok", content_type="text/plain"))
        )
        server_sock, client_sock = socket.socketpair()
        server_reader, server_writer = await asyncio.open_connection(sock=server_sock)
        _, client_writer = await asyncio.open_connection(sock=client_sock)
        conn = Connection(
            worker.app,
            server_reader,
            server_writer,
            ("127.0.0.1", 12345),
            ("127.0.0.1", 80),
        )
        try:
            client_writer.write(_GET)
            await client_writer.drain()
            # Worker._serve_connection catches and logs, so the coroutine
            # finishes cleanly and nothing escapes to asyncio.
            await asyncio.wait_for(worker._serve_connection(conn), timeout=5)
        finally:
            client_writer.close()
            conn.close()

    with caplog.at_level(logging.ERROR, logger="plain.server"):
        asyncio.run(scenario())

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Unexpected connection error"
    ]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert records[0].exc_info[0] is RuntimeError
