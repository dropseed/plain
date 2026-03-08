from __future__ import annotations

from typing import Any

from plain.http import Request

from .connection import WebSocketConnection


class WebSocketHandler:
    """WebSocket endpoint.

    The framework handles the HTTP upgrade handshake,
    then runs the WebSocket lifecycle as a coroutine on the event loop.

    Register via URL router like any other view::

        # urls.py
        path("chat/<room_id>/", ChatHandler)

    Example::

        class ChatHandler(WebSocketHandler):
            async def authorize(self):
                return self.request.user.is_authenticated

            async def receive(self, ws, message):
                await ws.send(f"echo: {message}")
    """

    request: Request
    url_kwargs: dict[str, Any]

    def __init__(
        self,
        *,
        request: Request,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.request = request
        self.url_kwargs = url_kwargs or {}

    # Maximum incoming message size in bytes (after fragment reassembly).
    # Frames exceeding this are rejected with CLOSE_MESSAGE_TOO_BIG.
    max_message_size: int = 1 * 1024 * 1024  # 1 MiB

    # Maximum time to wait for a slow client to accept written data.
    send_timeout: float = 10.0

    # Interval in seconds between server-initiated ping frames.
    # Detects dead connections from network drops, proxy timeouts, etc.
    # Set to 0 to disable.
    ping_interval: float = 30.0

    async def authorize(self) -> bool:
        """Check if the WebSocket connection is allowed.

        Must be implemented by subclasses. Has access to
        self.request for auth checking. Return True to allow
        the connection, False to reject with 403.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement authorize()"
        )

    async def connect(self, ws: WebSocketConnection) -> None:
        """Called after the WebSocket connection is established.

        Override to perform setup like subscribing to channels.
        """
        pass

    async def receive(self, ws: WebSocketConnection, message: str | bytes) -> None:
        """Handle an incoming WebSocket message.

        Override to process incoming messages.
        """
        pass

    async def disconnect(self, ws: WebSocketConnection) -> None:
        """Called when the WebSocket connection closes.

        Override for cleanup logic.
        """
        pass
