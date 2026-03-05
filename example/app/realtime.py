from __future__ import annotations

from plain.http import Request
from plain.realtime import SSEView
from plain.views import WebSocketView


class EchoSSE(SSEView):
    """SSE echo endpoint for testing."""

    def authorize(self, request: Request) -> bool:
        return True

    def subscribe(self, request: Request) -> list[str]:
        return ["echo"]

    def transform(self, channel_name: str, payload: str) -> str:
        return payload


class EchoWebSocket(WebSocketView):
    """WebSocket echo endpoint for Autobahn conformance testing."""

    async def authorize(self) -> bool:
        return True

    async def receive(self, message: str | bytes) -> None:
        await self.send(message)
