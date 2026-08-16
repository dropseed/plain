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
from typing import Any

import h2.errors
import h2.events
from plain.http import Response
from server_stubs import h2_connect


class _Handler:
    """Stand-in for the server handler — responds when released."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.release.set()

    async def handle(self, request: Any, executor: Any) -> Response:
        await self.release.wait()
        return Response(b"ok", content_type="text/plain")


# The h2 socketpair harness (H2Client / h2_connect) lives in server_stubs
# and is shared with test_server_body_limits.
_connect = h2_connect


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


def test_inflight_stream_survives_keepalive_timeout() -> None:
    # SERVER_KEEPALIVE_TIMEOUT applies between requests — a stream whose
    # view is still running while the client sends no frames (slow view,
    # SSE with a quiet client) must not be GOAWAY'd when the idle wait
    # times out.
    async def scenario() -> None:
        shutdown_event = asyncio.Event()
        handler = _Handler()
        handler.release.clear()  # hold the stream open in the view
        client, server_task, executor = await _connect(
            handler, shutdown_event, keepalive_timeout=0.2
        )
        try:
            await client.request(1)
            await asyncio.sleep(0.7)  # several keepalive timeouts pass

            handler.release.set()
            response = await client.wait_for(
                lambda e: isinstance(e, h2.events.ResponseReceived) and e.stream_id == 1
            )
            assert isinstance(response, h2.events.ResponseReceived)
            assert dict(response.headers or [])[b":status"] == b"200"
        finally:
            server_task.cancel()
            executor.shutdown(wait=False)

    asyncio.run(scenario())


def test_idle_clock_restarts_when_stream_finishes() -> None:
    # The idle clock measures time since in-flight work ended, not since
    # the last inbound frame: a response that takes most of the keepalive
    # window must not leave the connection with only the window's
    # remainder of idle reuse (the premature close races the next pooled
    # request).
    async def scenario() -> None:
        shutdown_event = asyncio.Event()
        handler = _Handler()
        client, server_task, executor = await _connect(
            handler, shutdown_event, keepalive_timeout=1.0
        )
        try:
            # A first request/response drains the connection-setup acks,
            # so the held stream's HEADERS below are the genuinely last
            # inbound frames before the idle window.
            await client.request(1)
            await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamEnded) and e.stream_id == 1
            )

            # Hold the view for most of the keepalive window, then let
            # the response go out.
            handler.release.clear()
            await client.request(3)
            await asyncio.sleep(0.7)
            handler.release.set()
            await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamEnded) and e.stream_id == 3
            )

            # Idle past the original window's remainder (0.3s), but well
            # inside a fresh window counted from the stream's completion.
            await asyncio.sleep(0.6)

            await client.request(5)
            response = await client.wait_for(
                lambda e: isinstance(e, h2.events.ResponseReceived) and e.stream_id == 5
            )
            assert isinstance(response, h2.events.ResponseReceived)
            assert dict(response.headers or [])[b":status"] == b"200"
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
