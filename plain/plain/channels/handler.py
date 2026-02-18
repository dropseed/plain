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

log = logging.getLogger("plain.channels")


class SSEConnection:
    """Represents a single SSE client connection managed by the async event loop."""

    def __init__(
        self,
        sock_fd: int,
        channel: Channel,
        subscriptions: list[str],
    ) -> None:
        self.sock_fd = sock_fd
        self.channel = channel
        self.subscriptions = subscriptions
        self._socket: socket.socket | None = None
        self._closed = False

    def open(self) -> None:
        """Take ownership of the socket fd and send SSE response headers."""
        self._socket = socket.fromfd(self.sock_fd, socket.AF_INET, socket.SOCK_STREAM)
        # Close the duplicated fd since fromfd() dups it
        os.close(self.sock_fd)

        # Send HTTP response headers for SSE
        header_lines = ["HTTP/1.1 200 OK"]
        for name, value in SSE_HEADERS:
            header_lines.append(f"{name}: {value}")
        header_lines.append("")
        header_lines.append("")
        header_str = "\r\n".join(header_lines)
        self._socket.sendall(header_str.encode("utf-8"))

    def send_event(self, data: Any, event: str | None = None) -> bool:
        """Send an SSE event to the client. Returns False if the connection is dead."""
        if self._closed or self._socket is None:
            return False
        try:
            self._socket.sendall(format_sse_event(data, event=event))
            return True
        except OSError:
            self.close()
            return False

    def send_heartbeat(self) -> bool:
        """Send a heartbeat comment. Returns False if the connection is dead."""
        if self._closed or self._socket is None:
            return False
        try:
            self._socket.sendall(format_sse_comment("heartbeat"))
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

    def start(self) -> None:
        """Start the heartbeat loop."""
        self._heartbeat_task = asyncio.run_coroutine_threadsafe(
            self._heartbeat_loop(), self._loop
        ).result()  # This won't block because we schedule the coroutine

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to all connections."""
        while True:
            await asyncio.sleep(15)
            dead: list[SSEConnection] = []
            for conn in self._connections:
                if not conn.send_heartbeat():
                    dead.append(conn)
            for conn in dead:
                self._connections.remove(conn)
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
        """
        conn = SSEConnection(sock_fd, channel, subscriptions)
        try:
            conn.open()
            self._connections.append(conn)
            log.debug(
                "Accepted SSE connection for %s, %d total",
                channel.path,
                len(self._connections),
            )
        except OSError:
            log.debug("Failed to open SSE connection")
            conn.close()

    def dispatch_event(
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
                # Transform the payload using the channel's sync transform method
                # For now, run transform inline (it should be fast)
                # TODO: Use run_in_executor for potentially slow transforms
                try:
                    transformed = conn.channel.transform(channel_name, payload)
                except Exception:
                    log.exception("Error in channel transform")
                    continue

                if transformed is None:
                    continue

                if isinstance(transformed, dict):
                    data = json.dumps(transformed)
                else:
                    data = str(transformed)

                if not conn.send_event(data, event=channel_name):
                    dead.append(conn)

        for conn in dead:
            self._connections.remove(conn)

    def close_all(self) -> None:
        """Close all connections."""
        for conn in self._connections:
            conn.close()
        self._connections.clear()
