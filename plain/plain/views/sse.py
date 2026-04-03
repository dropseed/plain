from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from plain.http import AsyncStreamingResponse, Response

from .base import View


class ServerSentEventsView(View):
    """Server-Sent Events view.

    Subclass this and implement `stream()` to yield ServerSentEvent instances:

        class TimeView(ServerSentEventsView):
            async def stream(self):
                while True:
                    yield ServerSentEvent(data={"time": datetime.now().isoformat()})
                    await asyncio.sleep(1)
    """

    def get(self) -> AsyncStreamingResponse:
        return AsyncStreamingResponse(
            streaming_content=self._format_events(),
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def head(self) -> Response:
        return Response(
            content_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    async def stream(self) -> AsyncIterator[ServerSentEvent]:
        """Override this to yield ServerSentEvent instances."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement stream()")
        yield  # noqa: RET503 — unreachable, marks this as an async generator

    async def _format_events(self) -> AsyncIterator[str]:
        async for event in self.stream():
            yield event.format()


class ServerSentEvent:
    """An SSE event with optional event type, id, and retry fields.

    Usage:
        yield ServerSentEvent(data="hello")
        yield ServerSentEvent(data={"count": 1}, event="update")
        yield ServerSentEvent(data="hello", id="msg-1", retry=5000)
        yield ServerSentEvent.comment("keepalive")
    """

    __slots__ = ("_comment", "data", "event", "id", "retry")

    def __init__(
        self,
        data: Any,
        *,
        event: str | None = None,
        id: str | None = None,
        retry: int | None = None,
    ) -> None:
        self._comment: str | None = None
        self.data = data
        self.event = event
        self.id = id
        self.retry = retry

    @classmethod
    def comment(cls, text: str = "") -> ServerSentEvent:
        """Create an SSE comment (line starting with ':').

        Comments are ignored by EventSource but useful as keepalives
        to prevent proxies and browsers from closing idle connections.
        """
        instance = cls.__new__(cls)
        instance._comment = text
        instance.data = None
        instance.event = None
        instance.id = None
        instance.retry = None
        return instance

    def __repr__(self) -> str:
        if self._comment is not None:
            return f"ServerSentEvent.comment({self._comment!r})"
        parts = [repr(self.data)]
        if self.event is not None:
            parts.append(f"event={self.event!r}")
        if self.id is not None:
            parts.append(f"id={self.id!r}")
        if self.retry is not None:
            parts.append(f"retry={self.retry!r}")
        return f"ServerSentEvent({', '.join(parts)})"

    def format(self) -> str:
        """Format this event as an SSE event string."""
        # Comment-only event (keepalive)
        if self._comment is not None:
            return f": {self._comment}\n\n"

        lines: list[str] = []

        if self.event is not None:
            lines.append(f"event: {self.event}")

        if self.id is not None:
            lines.append(f"id: {self.id}")

        if self.retry is not None:
            lines.append(f"retry: {self.retry}")

        serialized = self.data if isinstance(self.data, str) else json.dumps(self.data)

        # SSE spec: each line of data gets its own "data:" prefix.
        # Use split("\n") instead of splitlines() to preserve empty and
        # trailing lines — splitlines() would drop them, altering the
        # payload clients receive.
        for line in serialized.split("\n"):
            lines.append(f"data: {line}")

        # Double newline terminates the event
        return "\n".join(lines) + "\n\n"
