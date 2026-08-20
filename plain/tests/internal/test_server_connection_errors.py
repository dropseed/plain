"""An unexpected exception in the h1 connection handler must be logged
by plain itself, not escape into asyncio's default exception handler.

The body-abort fix removed the known RuntimeError escape (Sentry
PULLAPPROVE5-7N), but handle_connection had no connection-level
catch-all — any future bug took the same route out: an "Unhandled
exception in client_connected_cb" record on the `asyncio` logger, which
plain never configures, with no traceback attribution. h2 already
catches at the connection level; this pins h1's equivalent.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from plain.http import Response
from plain.server.http import h1
from server_stubs import ResponseHandler, h1_connect, make_worker

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
        client = await h1_connect(worker)
        try:
            await client.send(_GET)
            # The connection task must finish cleanly — the RuntimeError
            # is caught and logged, never raised out of the coroutine.
            await asyncio.wait_for(client.server_task, timeout=5)
        finally:
            client.teardown()

    with caplog.at_level(logging.ERROR, logger="plain.server"):
        asyncio.run(scenario())

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Unexpected error in HTTP/1.1 connection"
    ]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert records[0].exc_info[0] is RuntimeError
