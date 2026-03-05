from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from typing import Any

from plain.http import ForbiddenError403, ResponseBase

from .base import View

logger = logging.getLogger("plain.request")


class WebSocketView(View):
    """View subclass for WebSocket connections.

    Always async. The framework handles the HTTP upgrade handshake,
    then runs the WebSocket lifecycle as a coroutine on the event loop.

    Note: The full middleware chain runs before the WebSocket upgrade
    occurs.  Response-modifying middleware (compression, header injection)
    sees the ``WebSocketUpgradeResponse`` marker — but the server replaces
    it with the raw 101 handshake, so middleware modifications are ignored.
    Middleware that short-circuits (e.g. auth returning 403) works normally.

    Register via URL router like any other view::

        # urls.py
        path("chat/<room_id>/", ChatView)

    Example::

        class ChatView(WebSocketView):
            async def authorize(self):
                return self.request.user.is_authenticated

            async def receive(self, message):
                await self.send(f"echo: {message}")
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._closed = False

    def bind_transport(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Bind the async transport after the WebSocket handshake completes.

        Called by the server's connection handler. Provides the reader/writer
        pair used by send() and close().
        """
        self._reader = reader
        self._writer = writer

    async def authorize(self) -> bool:
        """Check if the WebSocket connection is allowed.

        Override to implement authorization logic. Has access to
        self.request for auth checking.
        """
        return True

    async def connect(self) -> None:
        """Called after the WebSocket connection is established.

        Override to perform setup like subscribing to channels.
        """
        pass

    async def receive(self, message: str | bytes) -> None:
        """Handle an incoming WebSocket message.

        Override to process incoming messages.
        """
        pass

    async def disconnect(self) -> None:
        """Called when the WebSocket connection closes.

        Override for cleanup logic.
        """
        pass

    async def _after_connect(self) -> None:
        """Hook called after connect(). Override in subclasses for post-connect setup."""
        pass

    async def _before_disconnect(self) -> None:
        """Hook called before disconnect(). Override in subclasses for pre-disconnect cleanup."""
        pass

    # Maximum incoming message size in bytes (after fragment reassembly).
    # Frames exceeding this are rejected with CLOSE_MESSAGE_TOO_BIG.
    max_message_size: int = 1 * 1024 * 1024  # 1 MiB

    # Maximum time to wait for a slow client to accept written data.
    # If drain() doesn't complete in this time, the connection is closed.
    send_timeout: float = 10.0

    async def send(self, message: str | bytes) -> None:
        """Send a message to the WebSocket client.

        Closes the connection if the client can't keep up (drain times out).
        """
        if self._closed or self._writer is None:
            return

        from plain.server.protocols.websocket import OP_BINARY, OP_TEXT, encode_frame

        if isinstance(message, bytes):
            data = encode_frame(OP_BINARY, message)
        else:
            data = encode_frame(OP_TEXT, str(message).encode("utf-8"))

        self._writer.write(data)
        try:
            await asyncio.wait_for(self._writer.drain(), timeout=self.send_timeout)
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

        from plain.server.protocols.websocket import encode_close

        if self._writer:
            try:
                self._writer.write(encode_close(code, reason))
                await self._writer.drain()
            except OSError:
                pass

    async def get(self) -> ResponseBase:
        """Handle the WebSocket upgrade and lifecycle.

        This is called by the async view dispatch. It performs the
        upgrade handshake, then runs the receive loop.
        """
        # Authorization check
        authorized = await self.authorize()
        if not authorized:
            raise ForbiddenError403

        # Return a marker response that tells the server to perform
        # the WebSocket upgrade handshake and run the lifecycle.
        return WebSocketUpgradeResponse(self)


class WebSocketUpgradeResponse(ResponseBase):
    """Marker response that tells the server to perform a WebSocket upgrade.

    The server's connection handler checks for this response type and
    handles the upgrade handshake + WebSocket lifecycle.
    """

    status_code = 101
    streaming = True  # Skip Content-Length middleware

    def __init__(self, ws_view: WebSocketView, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ws_view = ws_view
        self.log_access = False

    def __iter__(self) -> Iterator[bytes]:
        # Required by ResponseBase interface.  Never actually iterated —
        # the server intercepts this response type before writing.
        return iter([])
