"""Async handler for SSE connections.

This module contains the async infrastructure that runs in the worker's
background event loop thread. The developer never imports or uses this
directly — it's internal framework plumbing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from typing import TYPE_CHECKING, Any

from .sse import SSE_HEADERS, format_sse_comment, format_sse_event

if TYPE_CHECKING:
    from .channel import Channel
    from .listener import PostgresListener

log = logging.getLogger("plain.channels")

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
        """Take ownership of the socket fd and send SSE response headers."""
        self._socket = socket.fromfd(self.sock_fd, socket.AF_INET, socket.SOCK_STREAM)
        # Close the duplicated fd since fromfd() dups it
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


class AsyncConnectionManager:
    """Manages SSE connections on the async event loop.

    One instance per worker process. Handles:
    - Accepting new SSE connections (socket handoff from sync worker)
    - Heartbeat pings to detect dead connections
    - Event dispatch from Postgres NOTIFY to SSE clients
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._connections: list[SSEConnection] = []
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
        """Start listening on Postgres channels for a new SSE connection."""
        if self._listener is None:
            return
        for channel in subscriptions:
            self._channel_refcounts[channel] = (
                self._channel_refcounts.get(channel, 0) + 1
            )
            if self._channel_refcounts[channel] == 1:
                # First subscriber — start listening
                await self._listener.listen(channel)

    async def _unsubscribe_channels(self, subscriptions: list[str]) -> None:
        """Stop listening on Postgres channels when an SSE connection closes."""
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
            dead: list[SSEConnection] = []
            for conn in self._connections:
                if not await conn.send_heartbeat():
                    dead.append(conn)
            for conn in dead:
                self._connections.remove(conn)
                await self._unsubscribe_channels(conn.subscriptions)
                log.debug(
                    "Removed dead SSE connection, %d remaining",
                    len(self._connections),
                )

    def accept_connection(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
    ) -> None:
        """Accept a new SSE connection from the sync worker.

        Called via loop.call_soon_threadsafe() from the sync worker thread.
        Schedules the async setup as a task on the event loop.
        """
        self._loop.create_task(
            self._accept_connection_async(sock_fd, channel, subscriptions)
        )

    async def _accept_connection_async(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
    ) -> None:
        """Async implementation of accept_connection."""
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

    async def dispatch_event(
        self,
        channel_name: str,
        payload: str,
    ) -> None:
        """Dispatch a Postgres NOTIFY event to all matching SSE connections.

        Called from the async event loop when a NOTIFY arrives.
        """
        dead: list[SSEConnection] = []
        for conn in self._connections:
            if channel_name in conn.subscriptions:
                # Run the sync transform in a thread to avoid blocking the loop
                try:
                    transformed = await self._loop.run_in_executor(
                        None, conn.channel.transform, channel_name, payload
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
        """Close all SSE connections."""
        for conn in self._connections:
            conn.close()
        self._connections.clear()
        self._channel_refcounts.clear()
