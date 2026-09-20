"""WebSockets through the h1 connection loop, on a socketpair.

A real `BaseHandler` runs the test app's views, so the handshake goes
through middleware and `View.get_response()` exactly as in production;
the socket then runs over `Connection` with `run_websocket`. The client
half speaks masked frames with the same codec.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry import trace
from plain.http.websocket_frames import (
    OP_BINARY,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    encode_frame,
)
from plain.internal.handlers.base import BaseHandler
from plain.runtime import settings
from plain.test.otel import install_test_tracer
from server_stubs import H1Client, LogCapture, capture_logger, h1_connect, make_worker
from websocket_helpers import (
    UPGRADE_ACCEPT,
    client_close,
    client_frame,
    close_code,
    read_server_frame,
    upgrade_request,
)

_span_exporter = install_test_tracer()


@pytest.fixture
def request_log() -> Iterator[LogCapture]:
    with capture_logger("plain.request") as capture:
        yield capture


@pytest.fixture
def access_log() -> Iterator[LogCapture]:
    with capture_logger("plain.server.access") as capture:
        yield capture


@pytest.fixture(autouse=True)
def _spans_clean() -> None:
    _span_exporter.clear()


@pytest.fixture(autouse=True)
def _plain_http() -> Any:
    """The socketpair is plain HTTP; keep the HTTPS redirect out of the way."""
    original = settings.HTTPS_REDIRECT_ENABLED
    settings.HTTPS_REDIRECT_ENABLED = False
    try:
        yield
    finally:
        settings.HTTPS_REDIRECT_ENABLED = original


def _worker() -> Any:
    handler = BaseHandler()
    handler.load_middleware()
    return make_worker(handler=handler)


async def _upgrade(
    worker: Any, path: str = "/websocket/echo", **kwargs: Any
) -> tuple[H1Client, bytes]:
    client = await h1_connect(worker)
    await client.send(upgrade_request(path, **kwargs))
    headers = await client.read_headers()
    return client, headers


def test_upgrade_header_block() -> None:
    async def run() -> None:
        worker = _worker()
        client, headers = await _upgrade(worker, protocols="binary, echo")
        try:
            lines = headers.decode().split("\r\n")
            assert lines[0] == "HTTP/1.1 101 Switching Protocols"
            lowered = {
                line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip()
                for line in lines[1:]
                if ":" in line
            }
            assert lowered["upgrade"] == "websocket"
            assert lowered["connection"] == "Upgrade"
            assert lowered["sec-websocket-accept"] == UPGRADE_ACCEPT
            # The client's order wins: "binary" was offered first.
            assert lowered["sec-websocket-protocol"] == "binary"
            assert "content-length" not in lowered
            assert "transfer-encoding" not in lowered
        finally:
            client.teardown()

    asyncio.run(run())


def test_echo_text_and_binary_then_close() -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker)
        try:
            await client.send(client_frame(OP_TEXT, "héllo".encode()))
            frame = await read_server_frame(client.reader)
            assert (frame.opcode, frame.payload) == (OP_TEXT, "héllo".encode())

            await client.send(client_frame(OP_BINARY, bytes(range(256))))
            frame = await read_server_frame(client.reader)
            assert (frame.opcode, frame.payload) == (OP_BINARY, bytes(range(256)))

            await client.send(client_close(1000, "done"))
            frame = await read_server_frame(client.reader)
            assert close_code(frame) == 1000
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(run())


def test_fragments_with_ping_between_reassemble() -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker)
        try:
            await client.send(client_frame(OP_TEXT, b"one ", fin=False))
            await client.send(client_frame(OP_PING, b"tick"))
            await client.send(client_frame(OP_CONTINUATION, b"two", fin=True))

            pong = await read_server_frame(client.reader)
            assert (pong.opcode, pong.payload) == (OP_PONG, b"tick")
            echoed = await read_server_frame(client.reader)
            assert (echoed.opcode, echoed.payload) == (OP_TEXT, b"one two")
        finally:
            client.teardown()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("path", "frame", "expected_code"),
    [
        ("/websocket/small", client_frame(OP_TEXT, b"x" * 17), 1009),
        ("/websocket/echo", encode_frame(OP_TEXT, b"unmasked"), 1002),
        ("/websocket/echo", client_frame(OP_TEXT, b"\xff\xfe"), 1007),
    ],
    ids=["too-big", "unmasked", "invalid-utf8"],
)
def test_protocol_failures_close_with_the_right_code(
    path: str, frame: bytes, expected_code: int
) -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker, path)
        try:
            await client.send(frame)
            close = await read_server_frame(client.reader)
            assert close_code(close) == expected_code
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(run())


def test_peer_vanishing_is_a_quiet_ending(request_log: LogCapture) -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker)
        try:
            client.writer.close()
            await asyncio.wait_for(client.server_task, timeout=5)
        finally:
            client.teardown()

    asyncio.run(run())
    assert [r for r in request_log.records if r.levelno >= logging.ERROR] == []


def test_send_after_peer_left_is_a_quiet_ending(request_log: LogCapture) -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker, "/websocket/talks")
        try:
            await client.send(client_close(1000))
            close = await read_server_frame(client.reader)
            assert close_code(close) == 1000
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(run())
    assert [r for r in request_log.records if r.levelno >= logging.ERROR] == []


def test_view_exception_closes_1011_and_is_logged_on_a_span(
    request_log: LogCapture,
) -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker, "/websocket/raises")
        try:
            close = await read_server_frame(client.reader)
            assert close_code(close) == 1011
            # Answer the close handshake as a browser does.
            await client.send(client_close(1011))
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(run())

    errors = [r for r in request_log.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert "websocket view boom" in str(errors[0].exc_info[1])

    socket_spans = [
        s for s in _span_exporter.get_finished_spans() if s.name.startswith("WEBSOCKET")
    ]
    assert len(socket_spans) == 1
    span = socket_spans[0]
    assert span.kind == trace.SpanKind.SERVER
    assert span.name == "WEBSOCKET /websocket/raises"
    assert span.status.status_code == trace.StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.attributes["http.response.status_code"] == 101
    assert len(span.links) == 1
    # The log record was made inside the socket span.
    assert errors[0].captured_span_id == span.context.span_id  # ty: ignore[unresolved-attribute]


def test_shutdown_sends_1001_and_cancels_the_view() -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker, "/websocket/sleeps")
        try:
            worker.alive = False
            worker.shutdown_event.set()
            close = await read_server_frame(client.reader, timeout=1.0)
            assert close_code(close) == 1001
            # Answer the close handshake as a well-behaved client would.
            await client.send(client_close(1001))
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(run())


def test_bytes_behind_the_handshake_refuse_the_upgrade(access_log: LogCapture) -> None:
    async def run() -> None:
        worker = _worker()
        client = await h1_connect(worker)
        try:
            await client.send(upgrade_request() + client_frame(OP_TEXT, b"early"))
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 503 ")
            assert b"101" not in headers.split(b"\r\n")[0]
        finally:
            client.teardown()

    asyncio.run(run())
    assert [r.__dict__.get("status") for r in access_log.records] == [503]


def test_draining_worker_refuses_the_upgrade() -> None:
    async def run() -> None:
        worker = _worker()
        worker.alive = False
        client, headers = await _upgrade(worker)
        try:
            assert headers.startswith(b"HTTP/1.1 503 ")
        finally:
            client.teardown()

    asyncio.run(run())


def test_past_the_keepalive_budget_still_upgrades() -> None:
    async def run() -> None:
        worker = _worker()
        worker.nr_conns = worker.max_keepalived + 1
        client, headers = await _upgrade(worker)
        try:
            assert headers.startswith(b"HTTP/1.1 101 ")
            await client.send(client_frame(OP_TEXT, b"hi"))
            frame = await read_server_frame(client.reader)
            assert frame.payload == b"hi"
        finally:
            client.teardown()

    asyncio.run(run())


def test_access_log_records_the_socket_once_at_close(access_log: LogCapture) -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker)
        try:
            assert access_log.records == []
            await client.send(client_close(1000))
            await read_server_frame(client.reader)
            await client.assert_closed()
        finally:
            client.teardown()

    asyncio.run(run())
    assert [r.__dict__.get("status") for r in access_log.records] == [101]


def test_plain_get_to_a_websocket_view_runs_get() -> None:
    async def run() -> None:
        worker = _worker()
        client = await h1_connect(worker)
        try:
            await client.send(
                b"GET /websocket/echo HTTP/1.1\r\nHost: testserver\r\n\r\n"
            )
            headers, body = await client.read_response()
            assert headers.startswith(b"HTTP/1.1 200 ")
            assert body == b"websocket page"
        finally:
            client.teardown()

    asyncio.run(run())


def test_peer_close_ends_a_view_that_is_not_reading(access_log: LogCapture) -> None:
    """The sleeping view never touches `ws`; the peer's CLOSE must still end
    the connection task (and run the closers) within the grace period."""

    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker, "/websocket/sleeps")
        try:
            await client.send(client_close(1000))
            close = await read_server_frame(client.reader)
            assert close_code(close) == 1000
            await asyncio.wait_for(client.server_task, timeout=3)
        finally:
            client.teardown()

    asyncio.run(run())
    assert [r.__dict__.get("status") for r in access_log.records] == [101]


def test_peer_vanishing_ends_a_view_that_is_not_reading() -> None:
    async def run() -> None:
        worker = _worker()
        client, _ = await _upgrade(worker, "/websocket/sleeps")
        try:
            client.writer.close()
            await asyncio.wait_for(client.server_task, timeout=3)
        finally:
            client.teardown()

    asyncio.run(run())
