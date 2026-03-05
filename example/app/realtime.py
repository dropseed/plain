from __future__ import annotations

from plain.http import Request
from plain.realtime import Channel, realtime_registry


@realtime_registry.register
class EchoChannel(Channel):
    """WebSocket echo channel for conformance testing."""

    path = "/ws-echo/"

    def authorize(self, request: Request) -> bool:
        return True

    def subscribe(self, request: Request) -> list[str]:
        return ["echo"]

    def receive(self, message: str | bytes) -> str | bytes:
        return message
