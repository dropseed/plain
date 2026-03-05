from __future__ import annotations

import asyncio
from typing import Any

from plain.views import WebSocketView

from .channel import pg_listen


class RealtimeWebSocketView(WebSocketView):
    """WebSocketView with Postgres LISTEN/NOTIFY subscription support.

    Adds `subscribe()` for server-push events over WebSocket connections.

    Example::

        class ChatSocket(RealtimeWebSocketView):
            async def authorize(self):
                return self.request.user.is_authenticated

            async def connect(self):
                await self.subscribe(f"chat:{self.url_kwargs['room_id']}")

            async def receive(self, message):
                await self.send(f"echo: {message}")
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._subscriptions: list[str] = []
        self._listen_tasks: list[asyncio.Task] = []

    async def subscribe(self, channel: str) -> None:
        """Subscribe to a Postgres NOTIFY channel for server-push events."""
        self._subscriptions.append(channel)

    async def _after_connect(self) -> None:
        """Start pg_listen tasks for all subscriptions after connect()."""
        if self._subscriptions:
            loop = asyncio.get_running_loop()
            for channel in self._subscriptions:
                task = loop.create_task(self._pg_listen(channel))
                self._listen_tasks.append(task)

    async def _before_disconnect(self) -> None:
        """Cancel all pg_listen tasks before disconnect()."""
        for task in self._listen_tasks:
            task.cancel()
        if self._listen_tasks:
            await asyncio.gather(*self._listen_tasks, return_exceptions=True)
        self._listen_tasks.clear()

    async def _pg_listen(self, channel: str) -> None:
        """Listen for Postgres NOTIFY and send to WebSocket client."""
        try:
            async for channel_name, payload in pg_listen(channel):
                if self._closed:
                    break
                if channel_name is None:
                    continue  # heartbeat
                await self.send(payload)
        except asyncio.CancelledError:
            pass
