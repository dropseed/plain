"""An aborted request body must not crash the connection handler.

When a client stalls mid-body, recv_more times out, cancels its pending
read task, and raises _IncompleteBody so the handler can answer 408 and
linger-close. Before the cancellation has unwound, the reader is still
occupied — and the linger path immediately reads the same connection.
Without waiting for the unwind, that second read raised RuntimeError
("read() called while another coroutine is already waiting for incoming
data") and escaped handle_connection unhandled (production incident:
Sentry PULLAPPROVE5-7N).
"""

from __future__ import annotations

import asyncio

import pytest
from plain.http import Response
from plain.server.http import h1
from server_stubs import ResponseHandler, h1_connect, make_worker


def test_stalled_body_gets_408_without_crashing_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Shrink the per-recv body timeout so the stall is detected quickly.
    monkeypatch.setattr(h1, "BODY_RECV_TIMEOUT", 0.2)

    async def scenario() -> None:
        worker = make_worker(
            handler=ResponseHandler(lambda: Response(b"ok", content_type="text/plain"))
        )
        client = await h1_connect(worker)
        try:
            # Declare 10 body bytes, send 3, then stall.
            await client.send(
                b"POST / HTTP/1.1\r\nHost: testserver\r\nContent-Length: 10\r\n\r\nabc"
            )

            headers, _body = await client.read_response()
            assert headers.startswith(b"HTTP/1.1 408")

            # The client gives up; the linger read sees EOF and the
            # handler must exit cleanly — the RuntimeError escaped right
            # here before the fix.
            client.writer.close()
            await asyncio.wait_for(client.server_task, timeout=5)
        finally:
            client.teardown()

    asyncio.run(scenario())
