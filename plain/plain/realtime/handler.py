"""Async handler for real-time connections (SSE and WebSocket).

This module contains the async infrastructure that runs in the worker's
background event loop thread. The developer never imports or uses this
directly — it's internal framework plumbing.

This is the only async code in the realtime system. All application-facing
APIs (Channel.authorize, .subscribe, .transform, .receive) are sync and
called via run_in_executor() when needed. See ARCHITECTURE.md for why.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from typing import TYPE_CHECKING, Any

from .sse import SSE_HEADERS, format_sse_comment, format_sse_event
from .websocket import (
    CLOSE_INTERNAL_ERROR,
    CLOSE_INVALID_PAYLOAD,
    CLOSE_NORMAL,
    CLOSE_PROTOCOL_ERROR,
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    encode_close,
    encode_frame,
    parse_close_payload,
    read_frame,
)

if TYPE_CHECKING:
    from .channel import Channel
    from .listener import PostgresListener

log = logging.getLogger("plain.realtime")


async def _invoke(loop: asyncio.AbstractEventLoop, func: Any, *args: Any) -> Any:
    """Call a Channel method, supporting both sync and async implementations."""
    if asyncio.iscoroutinefunction(func):
        return await func(*args)
    return await loop.run_in_executor(None, func, *args)


# Socket send timeout in seconds — prevents blocking the async thread
# if a client stops reading.
_SOCKET_SEND_TIMEOUT = 5.0


class SSEConnection:
    """Represents a single SSE client connection managed by the async event loop."""

    def __init__(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.sock_fd = sock_fd
        self.channel = channel
        self.subscriptions = subscriptions
        self._loop = loop
        self._socket: socket.socket | None = None
        self._closed = False

    def open(self) -> None:
        """Take ownership of the socket fd and send SSE response headers.

        The fd was duplicated via os.dup() in the sync worker thread before
        handoff. fromfd() dups again, so we close the intermediate fd.
        See ARCHITECTURE.md "Socket handoff via os.dup()" for the full sequence.
        """
        self._socket = socket.fromfd(self.sock_fd, socket.AF_INET, socket.SOCK_STREAM)
        os.close(self.sock_fd)

        # Set a send timeout so blocking sends don't stall the async thread
        self._socket.settimeout(_SOCKET_SEND_TIMEOUT)

        # Send HTTP response headers for SSE
        header_lines = ["HTTP/1.1 200 OK"]
        for name, value in SSE_HEADERS:
            header_lines.append(f"{name}: {value}")
        header_lines.append("")
        header_lines.append("")
        header_str = "\r\n".join(header_lines)
        self._socket.sendall(header_str.encode("utf-8"))

    async def send_event(self, data: Any, event: str | None = None) -> bool:
        """Send an SSE event to the client. Returns False if the connection is dead."""
        if self._closed or self._socket is None:
            return False
        try:
            payload = format_sse_event(data, event=event)
            await self._loop.run_in_executor(None, self._socket.sendall, payload)
            return True
        except OSError:
            self.close()
            return False

    async def send_heartbeat(self) -> bool:
        """Send a heartbeat comment. Returns False if the connection is dead."""
        if self._closed or self._socket is None:
            return False
        try:
            payload = format_sse_comment("heartbeat")
            await self._loop.run_in_executor(None, self._socket.sendall, payload)
            return True
        except OSError:
            self.close()
            return False

    def close(self) -> None:
        """Close the connection."""
        if not self._closed:
            self._closed = True
            if self._socket:
                try:
                    self._socket.close()
                except OSError:
                    pass


class WebSocketConnection:
    """Represents a single WebSocket client connection on the async event loop.

    After the handshake completes (done by the sync worker), this class
    reads frames, handles control frames (ping/pong/close), dispatches
    text/binary messages to channel.receive(), and sends server-push
    events from Postgres NOTIFY.
    """

    def __init__(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.sock_fd = sock_fd
        self.channel = channel
        self.subscriptions = subscriptions
        self._loop = loop
        self._socket: socket.socket | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._closed = False
        self._read_task: asyncio.Task | None = None

    async def open(self) -> None:
        """Take ownership of the socket fd and set up async streams."""
        self._socket = socket.fromfd(self.sock_fd, socket.AF_INET, socket.SOCK_STREAM)
        os.close(self.sock_fd)
        self._socket.setblocking(False)

        # Wrap in asyncio streams for buffered reads
        self._reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self._reader)
        transport, _ = await self._loop.create_connection(
            lambda: protocol, sock=self._socket
        )
        self._writer = asyncio.StreamWriter(
            transport, protocol, self._reader, self._loop
        )

    def start_reading(self) -> None:
        """Start the frame reading loop as a background task."""
        self._read_task = self._loop.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Read WebSocket frames and dispatch messages."""
        assert self._reader is not None

        # Fragmentation state
        frag_opcode: int | None = None
        frag_payload = bytearray()

        try:
            while not self._closed:
                try:
                    frame = await read_frame(self._reader)
                except (asyncio.IncompleteReadError, ConnectionError):
                    break
                except ValueError as e:
                    log.debug("WebSocket protocol error: %s", e)
                    await self._send_close(CLOSE_PROTOCOL_ERROR, str(e))
                    break

                if frame.opcode == OP_CLOSE:
                    close = parse_close_payload(frame.payload)
                    await self._send_close(close.code)
                    break

                if frame.opcode == OP_PING:
                    await self._send_frame(OP_PONG, frame.payload)
                    continue

                if frame.opcode == OP_PONG:
                    continue

                # Data frames (text, binary, continuation)
                if frame.opcode == OP_CONTINUATION:
                    if frag_opcode is None:
                        await self._send_close(
                            CLOSE_PROTOCOL_ERROR, "Unexpected continuation"
                        )
                        break
                    frag_payload.extend(frame.payload)
                    if frame.fin:
                        await self._dispatch_message(frag_opcode, bytes(frag_payload))
                        frag_opcode = None
                        frag_payload.clear()
                elif frame.opcode in (OP_TEXT, OP_BINARY):
                    if frag_opcode is not None:
                        await self._send_close(
                            CLOSE_PROTOCOL_ERROR, "New data frame during fragmentation"
                        )
                        break
                    if frame.fin:
                        await self._dispatch_message(frame.opcode, frame.payload)
                    else:
                        frag_opcode = frame.opcode
                        frag_payload.extend(frame.payload)
        except Exception:
            log.exception("WebSocket read loop error")
        finally:
            self.close()

    async def _dispatch_message(self, opcode: int, payload: bytes) -> None:
        """Dispatch a complete message to channel.receive()."""
        try:
            if opcode == OP_TEXT:
                # Validate UTF-8
                try:
                    message: str | bytes = payload.decode("utf-8")
                except UnicodeDecodeError:
                    await self._send_close(CLOSE_INVALID_PAYLOAD, "Invalid UTF-8")
                    return
            else:
                message = payload

            result = await _invoke(self._loop, self.channel.receive, message)

            # If receive() returns a value, send it back
            if result is not None:
                if isinstance(result, bytes):
                    await self._send_frame(OP_BINARY, result)
                else:
                    await self._send_frame(OP_TEXT, str(result).encode("utf-8"))
        except Exception:
            log.exception("Error in channel.receive()")
            await self._send_close(CLOSE_INTERNAL_ERROR)

    async def send_event(self, data: Any, event: str | None = None) -> bool:
        """Send a server-push event as a text frame."""
        if self._closed:
            return False
        try:
            if isinstance(data, dict):
                text = json.dumps(data)
            else:
                text = str(data)

            # Include event type in the JSON if provided
            if event:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        parsed["_channel"] = event
                        text = json.dumps(parsed)
                except (json.JSONDecodeError, TypeError):
                    text = json.dumps({"_channel": event, "data": text})

            await self._send_frame(OP_TEXT, text.encode("utf-8"))
            return True
        except OSError:
            self.close()
            return False

    async def send_heartbeat(self) -> bool:
        """Send a WebSocket ping frame."""
        if self._closed:
            return False
        try:
            await self._send_frame(OP_PING, b"")
            return True
        except OSError:
            self.close()
            return False

    async def _send_frame(self, opcode: int, payload: bytes = b"") -> None:
        """Send a WebSocket frame."""
        if self._writer is None or self._closed:
            return
        data = encode_frame(opcode, payload)
        self._writer.write(data)
        await self._writer.drain()

    async def _send_close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Send a close frame and mark connection as closed."""
        if self._closed:
            return
        try:
            data = encode_close(code, reason)
            if self._writer:
                self._writer.write(data)
                await self._writer.drain()
        except OSError:
            pass
        self.close()

    def close(self) -> None:
        """Close the connection."""
        if not self._closed:
            self._closed = True
            if self._writer:
                try:
                    self._writer.close()
                except OSError:
                    pass
            elif self._socket:
                try:
                    self._socket.close()
                except OSError:
                    pass


class AsyncConnectionManager:
    """Manages real-time connections (SSE, WebSocket, and H2 SSE) on the async event loop.

    One instance per worker process. Handles:
    - Accepting new connections (socket handoff from worker thread)
    - Heartbeat pings to detect dead connections
    - Event dispatch from Postgres NOTIFY to connected clients
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._connections: list[Any] = []
        self._heartbeat_task: asyncio.Task | None = None
        self._listener: PostgresListener | None = None
        # Track subscription counts so we can UNLISTEN when no clients remain
        self._channel_refcounts: dict[str, int] = {}

    def start(self) -> None:
        """Start the heartbeat loop and Postgres listener. Must be called on the event loop."""
        self._heartbeat_task = self._loop.create_task(self._heartbeat_loop())
        self._loop.create_task(self._start_listener())

    async def _start_listener(self) -> None:
        """Start the Postgres LISTEN connection."""
        from .listener import PostgresListener

        self._listener = PostgresListener(self._loop, self)
        await self._listener.start()

    async def _subscribe_channels(self, subscriptions: list[str]) -> None:
        """Start listening on Postgres channels for a new connection."""
        if self._listener is None:
            return
        for channel in subscriptions:
            self._channel_refcounts[channel] = (
                self._channel_refcounts.get(channel, 0) + 1
            )
            if self._channel_refcounts[channel] == 1:
                await self._listener.listen(channel)

    async def _unsubscribe_channels(self, subscriptions: list[str]) -> None:
        """Stop listening on Postgres channels when a connection closes."""
        if self._listener is None:
            return
        for channel in subscriptions:
            count = self._channel_refcounts.get(channel, 0)
            if count <= 1:
                self._channel_refcounts.pop(channel, None)
                await self._listener.unlisten(channel)
            else:
                self._channel_refcounts[channel] = count - 1

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to all connections."""
        while True:
            await asyncio.sleep(15)
            dead: list[Any] = []
            for conn in self._connections:
                if not await conn.send_heartbeat():
                    dead.append(conn)
            for conn in dead:
                self._connections.remove(conn)
                await self._unsubscribe_channels(conn.subscriptions)
                log.debug(
                    "Removed dead connection, %d remaining",
                    len(self._connections),
                )

    def accept_sse_connection(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
    ) -> None:
        """Accept a new SSE connection from the worker thread."""
        self._loop.create_task(self._accept_sse_async(sock_fd, channel, subscriptions))

    def accept_ws_connection(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
    ) -> None:
        """Accept a new WebSocket connection from the worker thread."""
        self._loop.create_task(self._accept_ws_async(sock_fd, channel, subscriptions))

    def accept_h2_connection(self, h2_conn: Any) -> None:
        """Accept an H2SSEConnection from the h2 frame loop thread.

        Unlike SSE/WS, no socket setup is needed — the h2 frame loop
        owns the socket. We just subscribe to Postgres channels.
        """
        self._loop.create_task(self._accept_h2_async(h2_conn))

    async def _accept_h2_async(self, h2_conn: Any) -> None:
        """Async implementation of H2 SSE accept."""
        self._connections.append(h2_conn)
        await self._subscribe_channels(h2_conn.subscriptions)
        log.debug(
            "Accepted H2 SSE connection for %s, %d total",
            h2_conn.channel.path,
            len(self._connections),
        )

    def remove_connection(self, conn: Any) -> None:
        """Remove a connection and unsubscribe its channels.

        Called via call_soon_threadsafe when a channel stream is reset
        or the h2 connection closes.
        """
        self._loop.create_task(self._remove_async(conn))

    async def _remove_async(self, conn: Any) -> None:
        """Async implementation of connection removal."""
        try:
            self._connections.remove(conn)
        except ValueError:
            return  # Already removed
        await self._unsubscribe_channels(conn.subscriptions)
        log.debug(
            "Removed H2 SSE connection, %d remaining",
            len(self._connections),
        )

    # Keep old name for backwards compat with tests
    accept_connection = accept_sse_connection

    async def _accept_sse_async(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
    ) -> None:
        """Async implementation of SSE accept."""
        conn = SSEConnection(sock_fd, channel, subscriptions, self._loop)
        try:
            conn.open()
            self._connections.append(conn)
            await self._subscribe_channels(subscriptions)
            log.debug(
                "Accepted SSE connection for %s, %d total",
                channel.path,
                len(self._connections),
            )
        except OSError:
            log.debug("Failed to open SSE connection")
            conn.close()

    async def _accept_ws_async(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
    ) -> None:
        """Async implementation of WebSocket accept."""
        conn = WebSocketConnection(sock_fd, channel, subscriptions, self._loop)
        try:
            await conn.open()
            self._connections.append(conn)
            await self._subscribe_channels(subscriptions)
            conn.start_reading()
            log.debug(
                "Accepted WebSocket connection for %s, %d total",
                channel.path,
                len(self._connections),
            )
        except OSError:
            log.debug("Failed to open WebSocket connection")
            conn.close()

    async def dispatch_event(
        self,
        channel_name: str,
        payload: str,
    ) -> None:
        """Dispatch a Postgres NOTIFY event to all matching connections."""
        dead: list[Any] = []
        for conn in self._connections:
            if channel_name in conn.subscriptions:
                try:
                    transformed = await _invoke(
                        self._loop, conn.channel.transform, channel_name, payload
                    )
                except Exception:
                    log.exception("Error in channel transform")
                    continue

                if transformed is None:
                    continue

                if isinstance(transformed, dict):
                    data = json.dumps(transformed)
                else:
                    data = str(transformed)

                if not await conn.send_event(data, event=channel_name):
                    dead.append(conn)

        for conn in dead:
            self._connections.remove(conn)

    async def stop(self) -> None:
        """Stop the listener and close all connections."""
        if self._listener is not None:
            await self._listener.stop()
        self.close_all()

    def close_all(self) -> None:
        """Close all connections."""
        for conn in self._connections:
            conn.close()
        self._connections.clear()
        self._channel_refcounts.clear()
