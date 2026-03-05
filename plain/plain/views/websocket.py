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

    Register via URL router like any other view::

        # urls.py
        path("chat/<room_id>/", ChatView)

    Example::

        class ChatView(WebSocketView):
            async def authorize(self):
                return self.request.user.is_authenticated

            async def connect(self):
                await self.subscribe(f"chat:{self.url_kwargs['room_id']}")

            async def receive(self, message):
                await self.send(f"echo: {message}")
    """

    view_protocol: str | None = "websocket"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._closed = False
        self._subscriptions: list[str] = []

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

    async def send(self, message: str | bytes) -> None:
        """Send a message to the WebSocket client."""
        if self._closed or self._writer is None:
            return

        from plain.realtime.websocket import OP_BINARY, OP_TEXT, encode_frame

        if isinstance(message, bytes):
            data = encode_frame(OP_BINARY, message)
        else:
            data = encode_frame(OP_TEXT, str(message).encode("utf-8"))

        self._writer.write(data)
        await self._writer.drain()

    async def send_json(self, data: Any) -> None:
        """Send JSON data to the WebSocket client."""
        await self.send(json.dumps(data))

    async def subscribe(self, channel: str) -> None:
        """Subscribe to a Postgres NOTIFY channel for server-push events."""
        self._subscriptions.append(channel)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the WebSocket connection."""
        if self._closed:
            return
        self._closed = True

        from plain.realtime.websocket import encode_close

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

        # The actual WebSocket lifecycle is handled by the server's
        # connection handler which detects view_protocol == "websocket"
        # and performs the upgrade handshake before calling into the
        # WebSocket lifecycle methods.
        #
        # This get() method returns a special marker response that
        # the server knows to handle as a WebSocket upgrade.
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
        return iter([])
