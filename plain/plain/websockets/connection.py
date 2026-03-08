from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Coroutine
from typing import Any, Protocol, runtime_checkable

from plain.server.protocols.websocket import (
    OP_BINARY,
    OP_PING,
    OP_TEXT,
    _compress,
    encode_close,
    encode_frame,
    read_messages,
)

logger = logging.getLogger("plain.request")


@runtime_checkable
class _WebSocketWriter(Protocol):
    """Minimal writer interface for WebSocket connections.

    Matches asyncio.StreamWriter in production and allows test fakes.
    """

    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...
    def is_closing(self) -> bool: ...
    def drain(self) -> Coroutine[Any, Any, None]: ...
    def wait_closed(self) -> Coroutine[Any, Any, None]: ...


class WebSocketConnection:
    """User-facing WebSocket connection object.

    Passed to WebSocketView lifecycle methods (connect, receive, disconnect).
    Wraps the asyncio transport and provides send/close/iterate methods.

    Supports ``async for message in ws:`` to iterate incoming messages.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: _WebSocketWriter,
        *,
        send_timeout: float = 10.0,
        max_message_size: int = 1 * 1024 * 1024,
        ping_interval: float = 30.0,
        permessage_deflate: bool = False,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._closed = False
        self._send_timeout = send_timeout
        self._max_message_size = max_message_size
        self._ping_interval = ping_interval
        self._permessage_deflate = permessage_deflate
        self._pong_received = asyncio.Event()
        self._pong_received.set()  # no outstanding ping initially
        self._ping_task: asyncio.Task[None] | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    async def send(self, message: str | bytes) -> None:
        """Send a message to the WebSocket client.

        Closes the connection if the client can't keep up (drain times out).
        """
        if self._closed:
            return

        if isinstance(message, bytes):
            payload = message
            opcode = OP_BINARY
        else:
            payload = message.encode("utf-8")
            opcode = OP_TEXT

        rsv1 = False
        if self._permessage_deflate:
            payload = _compress(payload)
            rsv1 = True

        data = encode_frame(opcode, payload, rsv1=rsv1)

        self._writer.write(data)
        try:
            await asyncio.wait_for(self._writer.drain(), timeout=self._send_timeout)
        except TimeoutError:
            logger.warning("WebSocket send timed out (slow client), closing connection")
            await self.close(1001, "Send timeout")

    async def send_json(self, data: Any) -> None:
        """Send JSON data to the WebSocket client."""
        await self.send(json.dumps(data))

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the WebSocket connection."""
        if self._closed:
            return
        self._closed = True

        try:
            self._writer.write(encode_close(code, reason))
            await asyncio.wait_for(self._writer.drain(), timeout=self._send_timeout)
        except (OSError, TimeoutError):
            pass

    def _on_pong(self) -> None:
        """Called by the protocol layer when a pong frame arrives."""
        self._pong_received.set()

    async def __aiter__(self) -> AsyncIterator[str | bytes]:
        """Iterate incoming messages. Handles ping/pong and close frames."""
        async for message in read_messages(
            self._reader,
            self._writer,
            is_closed=lambda: self._closed,
            close=self.close,
            on_pong=self._on_pong,
            max_message_size=self._max_message_size,
            permessage_deflate=self._permessage_deflate,
        ):
            yield message

    def start_ping_loop(self) -> None:
        """Start periodic ping keepalive if configured."""
        if self._ping_interval > 0:
            self._ping_task = asyncio.get_running_loop().create_task(self._ping_loop())

    async def stop_ping_loop(self) -> None:
        """Stop the ping keepalive task."""
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except (asyncio.CancelledError, Exception):
                pass
            self._ping_task = None

    async def _ping_loop(self) -> None:
        """Send periodic pings to detect dead connections."""
        while not self._closed:
            await asyncio.sleep(self._ping_interval)
            if self._closed:
                break

            if not self._pong_received.is_set():
                logger.debug("WebSocket ping timeout (no pong received)")
                await self.close(1001, "Ping timeout")
                break

            self._pong_received.clear()
            try:
                self._writer.write(encode_frame(OP_PING, b""))
                await asyncio.wait_for(self._writer.drain(), timeout=self._send_timeout)
            except (OSError, TimeoutError):
                break

    async def close_transport(self) -> None:
        """Close the underlying transport (reader/writer)."""
        try:
            if not self._writer.is_closing():
                self._writer.close()
                await self._writer.wait_closed()
        except OSError:
            pass
