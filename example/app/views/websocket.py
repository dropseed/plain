from __future__ import annotations

import asyncio
import json
from datetime import datetime

from plain.websockets import WebSocketConnection, WebSocketHandler


class EchoWebSocket(WebSocketHandler):
    """Echo WebSocket for Autobahn conformance testing.

    Echoes back any message it receives (text or binary).
    """

    max_message_size = 16 * 1024 * 1024  # 16 MiB for Autobahn tests

    async def authorize(self) -> bool:
        return True

    async def receive(self, ws: WebSocketConnection, message: str | bytes) -> None:
        await ws.send(message)


class ChatWebSocket(WebSocketHandler):
    """Chat-style WebSocket demo.

    Broadcasts messages to all connected clients with timestamps.
    In-memory only — works within a single process.
    """

    # In-memory client tracking (single-process only)
    _connected_clients: dict[ChatWebSocket, WebSocketConnection] = {}

    async def authorize(self) -> bool:
        return True

    async def _broadcast(self, data: dict) -> None:
        """Send to all connected clients concurrently."""
        clients = list(ChatWebSocket._connected_clients.values())
        if clients:
            await asyncio.gather(
                *(ws.send_json(data) for ws in clients),
                return_exceptions=True,
            )

    async def connect(self, ws: WebSocketConnection) -> None:
        self._message_count = 0
        ChatWebSocket._connected_clients[self] = ws
        count = len(ChatWebSocket._connected_clients)
        await self._broadcast(
            {
                "type": "system",
                "message": f"User joined. {count} connected.",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
        )

    async def receive(self, ws: WebSocketConnection, message: str | bytes) -> None:
        if isinstance(message, bytes):
            await ws.send(message)
            return

        self._message_count += 1
        now = datetime.now().isoformat(timespec="seconds")

        try:
            data = json.loads(message)
            text = data.get("message", message)
        except (json.JSONDecodeError, AttributeError):
            text = message

        # Broadcast to other clients
        others = {
            v: cws
            for v, cws in ChatWebSocket._connected_clients.items()
            if v is not self
        }
        if others:
            response = {
                "type": "message",
                "message": text,
                "timestamp": now,
                "count": self._message_count,
            }
            await asyncio.gather(
                *(cws.send_json(response) for cws in others.values()),
                return_exceptions=True,
            )

    async def disconnect(self, ws: WebSocketConnection) -> None:
        ChatWebSocket._connected_clients.pop(self, None)
        count = len(ChatWebSocket._connected_clients)
        await self._broadcast(
            {
                "type": "system",
                "message": f"User left. {count} connected.",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
        )
