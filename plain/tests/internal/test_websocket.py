"""`WebSocket` on its own, over a socketpair: keepalive, closing, buffering.

The server-level behaviour (handshake, echo, shutdown, logging) is in
test_server_websocket.py; this pins the message layer's edges directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from plain.http import WebSocket, WebSocketClosed
from plain.http import websocket as websocket_module
from plain.http.websocket import PING_INTERVAL, PING_TIMEOUT
from plain.http.websocket_frames import OP_CLOSE, OP_PING, OP_PONG, OP_TEXT
from server_stubs import StubApp, socketpair_connection
from websocket_helpers import client_close, client_frame, close_code, read_server_frame


@asynccontextmanager
async def _open(
    *,
    max_message_size: int = 1024,
    ping_interval: float = PING_INTERVAL,
    ping_timeout: float = PING_TIMEOUT,
) -> AsyncIterator[tuple[WebSocket, asyncio.StreamReader, asyncio.StreamWriter]]:
    """A started `WebSocket` on the server end of a socketpair, plus the client end."""
    conn, client_reader, client_writer = await socketpair_connection(StubApp())
    ws = WebSocket(
        conn,
        max_message_size=max_message_size,
        ping_interval=ping_interval,
        ping_timeout=ping_timeout,
    )
    try:
        async with ws:
            yield ws, client_reader, client_writer
    finally:
        client_writer.close()


async def _send(writer: asyncio.StreamWriter, data: bytes) -> None:
    writer.write(data)
    await writer.drain()


def test_unanswered_ping_closes_1001() -> None:
    async def run() -> None:
        async with _open(ping_interval=0.05, ping_timeout=0.05) as (ws, reader, _):
            ping = await read_server_frame(reader)
            assert ping.opcode == OP_PING
            close = await read_server_frame(reader)
            assert close_code(close) == 1001
            await asyncio.wait_for(ws._closed.wait(), 1)
            assert ws.close_code == 1001

    asyncio.run(run())


def test_answered_ping_keeps_the_socket_open() -> None:
    async def run() -> None:
        async with _open(ping_interval=0.05, ping_timeout=1.0) as (ws, reader, writer):
            for _ in range(3):
                ping = await read_server_frame(reader)
                assert ping.opcode == OP_PING
                await _send(writer, client_frame(OP_PONG, ping.payload))
            assert not ws.closed

    asyncio.run(run())


def test_close_from_another_task_ends_a_running_iteration() -> None:
    async def run() -> None:
        async with _open() as (ws, reader, writer):
            received: list[str | bytes] = []

            async def consume() -> None:
                async for message in ws:
                    received.append(message)

            consumer = asyncio.create_task(consume())
            await _send(writer, client_frame(OP_TEXT, b"first"))
            while not received:
                await asyncio.sleep(0)
            closing = asyncio.create_task(ws.close(1000, "enough"))
            close = await read_server_frame(reader)
            assert close_code(close) == 1000
            await _send(writer, client_close(1000))
            await asyncio.wait_for(closing, timeout=2)
            await asyncio.wait_for(consumer, timeout=2)
            assert received == ["first"]
            assert ws.closed

    asyncio.run(run())


def test_send_after_close_raises_with_the_close_code() -> None:
    async def run() -> None:
        async with _open() as (ws, reader, writer):
            await _send(writer, client_close(4000, "bye"))
            close = await read_server_frame(reader)
            assert close_code(close) == 4000
            async for _ in ws:
                raise AssertionError("no messages were sent")
            assert (ws.close_code, ws.close_reason) == (4000, "bye")
            with pytest.raises(WebSocketClosed) as excinfo:
                await ws.send("too late")
            assert (excinfo.value.code, excinfo.value.reason) == (4000, "bye")

    asyncio.run(run())


def test_peer_vanishing_ends_iteration_and_send_raises_1006() -> None:
    async def run() -> None:
        async with _open() as (ws, _, writer):
            writer.close()
            async for _ in ws:
                raise AssertionError("no messages were sent")
            assert ws.closed
            with pytest.raises(WebSocketClosed) as excinfo:
                await ws.send("anyone?")
            assert excinfo.value.code == 1006

    asyncio.run(run())


def test_control_frames_flow_while_the_view_is_not_reading() -> None:
    """A push-only view never iterates; PINGs from the peer are still answered
    while the bounded queue has room, and a late reader gets every message."""

    async def run() -> None:
        async with _open() as (ws, reader, writer):
            for i in range(8):
                await _send(writer, client_frame(OP_TEXT, f"queued {i}".encode()))
            await _send(writer, client_frame(OP_PING, b"alive?"))
            pong = await read_server_frame(reader)
            assert (pong.opcode, pong.payload) == (OP_PONG, b"alive?")
            got = [await ws.__anext__() for _ in range(8)]
            assert got == [f"queued {i}" for i in range(8)]

    asyncio.run(run())


def test_buffered_messages_are_delivered_after_the_peer_closes() -> None:
    """Closing while the queue holds messages does not lose them: the late
    reader drains the queue, then the iteration ends."""

    async def run() -> None:
        async with _open() as (ws, reader, writer):
            for i in range(4):
                await _send(writer, client_frame(OP_TEXT, f"m{i}".encode()))
            await _send(writer, client_close(1000))
            assert (await read_server_frame(reader)).opcode == OP_CLOSE
            await asyncio.wait_for(ws._closed.wait(), 1)
            got = [message async for message in ws]
            assert got == ["m0", "m1", "m2", "m3"]

    asyncio.run(run())


def test_close_is_idempotent() -> None:
    async def run() -> None:
        async with _open() as (ws, reader, writer):
            await _send(writer, client_close(1000))
            assert (await read_server_frame(reader)).opcode == OP_CLOSE
            await ws.close()
            await ws.close()
            assert ws.closed

    asyncio.run(run())


class _StuckTransport:
    """A peer that accepted the handshake and then stopped reading.

    Like a real transport, a pending write is woken with an error by
    `abort()`, and never by `close()` (which waits for a flush that will
    not come).
    """

    def __init__(self) -> None:
        self.aborted = asyncio.Event()
        self.closed = False

    async def recv(self, n: int) -> bytes:
        await self.aborted.wait()
        return b""

    async def sendall(self, data: bytes) -> None:
        await self.aborted.wait()
        raise ConnectionResetError("aborted")

    def close(self) -> None:
        self.closed = True

    def abort(self) -> None:
        self.aborted.set()


def test_send_to_a_peer_that_stopped_reading_aborts_the_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(websocket_module, "WRITE_TIMEOUT", 0.05)

    async def run() -> None:
        transport = _StuckTransport()
        ws = WebSocket(transport, max_message_size=1024, ping_interval=3600)
        async with ws:
            with pytest.raises(WebSocketClosed) as excinfo:
                await ws.send(b"x" * 10)
            assert excinfo.value.code == 1006
            assert transport.aborted.is_set()
            assert ws.closed

    asyncio.run(run())


def test_ping_timeout_behind_a_stuck_send_still_ends_the_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A view mid-`send` to a dead peer holds the write lock; the keepalive
    must end the socket anyway rather than queue behind it."""
    monkeypatch.setattr(websocket_module, "WRITE_TIMEOUT", 10.0)
    monkeypatch.setattr(websocket_module, "CLOSE_TIMEOUT", 0.05)

    async def run() -> None:
        transport = _StuckTransport()
        ws = WebSocket(
            transport, max_message_size=1024, ping_interval=0.05, ping_timeout=0.05
        )
        async with ws:
            sender = asyncio.create_task(ws.send(b"stuck"))
            await asyncio.wait_for(ws.wait_closed(), 2)
            assert transport.aborted.is_set()
            with pytest.raises(WebSocketClosed):
                await sender

    asyncio.run(run())


def test_full_receive_buffer_closes_with_1008_at_the_next_ping() -> None:
    """The peer answers every ping, but the view never iterates: once the
    buffer is full nothing is read, and the close says whose fault that is."""

    async def run() -> None:
        async with _open(ping_interval=0.05, ping_timeout=0.1) as (ws, reader, writer):
            for i in range(websocket_module.RECEIVE_QUEUE_SIZE + 2):
                await _send(writer, client_frame(OP_TEXT, f"{i}".encode()))
            while True:
                frame = await read_server_frame(reader, timeout=2)
                if frame.opcode == OP_PING:
                    await _send(writer, client_frame(OP_PONG, frame.payload))
                    continue
                assert close_code(frame) == 1008
                break
            await asyncio.wait_for(ws.wait_closed(), 1)

    asyncio.run(run())


class _SlowTransport(_StuckTransport):
    """Accepts the first chunk of a write, then stops draining."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks = 0

    async def sendall(self, data: bytes) -> None:
        self.chunks += 1
        if self.chunks == 1:
            return
        await super().sendall(data)


def test_a_send_cancelled_mid_frame_ends_the_socket() -> None:
    """Half a frame on the wire cannot be recovered from: whatever went out
    next would be read as its payload, so the socket ends instead."""

    async def run() -> None:
        transport = _SlowTransport()
        ws = WebSocket(transport, max_message_size=1024, ping_interval=3600)
        async with ws:
            sending = asyncio.create_task(
                ws.send(b"x" * (websocket_module.WRITE_CHUNK * 2))
            )
            while transport.chunks < 2:
                await asyncio.sleep(0)
            sending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sending
            assert ws.closed
            assert transport.aborted.is_set()
            with pytest.raises(WebSocketClosed):
                await ws.send("next")

    asyncio.run(run())


def test_control_frames_are_not_subject_to_the_message_cap() -> None:
    async def run() -> None:
        async with _open(max_message_size=10) as (ws, reader, writer):
            await _send(writer, client_frame(OP_PING, b"twenty bytes of ping"))
            pong = await read_server_frame(reader)
            assert (pong.opcode, pong.payload) == (OP_PONG, b"twenty bytes of ping")
            assert not ws.closed

    asyncio.run(run())
