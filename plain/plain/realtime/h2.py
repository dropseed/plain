"""HTTP/2 SSE connection for realtime.

Implements the same duck-type interface as SSEConnection so the
AsyncConnectionManager can treat it identically. The key difference
is that this class never touches the h2 state machine or socket
directly — it only enqueues data into the H2ConnectionState's
thread-safe outbound queue.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .sse import format_sse_comment, format_sse_event

if TYPE_CHECKING:
    from plain.server.http.h2handler import H2ConnectionState

    from .channel import Channel


class H2SSEConnection:
    """SSE connection over an HTTP/2 stream.

    The async event loop thread calls send_event/send_heartbeat, which
    enqueue SSE-formatted bytes into the H2ConnectionState. The h2
    frame loop thread drains the queue and sends DATA frames.
    """

    def __init__(
        self,
        state: H2ConnectionState,
        stream_id: int,
        channel: Channel,
        subscriptions: list[str],
    ) -> None:
        self.state = state
        self.stream_id = stream_id
        self.channel = channel
        self.subscriptions = subscriptions
        self._closed = False

    async def send_event(self, data: Any, event: str | None = None) -> bool:
        if self._closed:
            return False
        try:
            payload = format_sse_event(data, event=event)
            self.state.enqueue_data(self.stream_id, payload)
            return True
        except Exception:
            self.close()
            return False

    async def send_heartbeat(self) -> bool:
        if self._closed:
            return False
        try:
            payload = format_sse_comment("heartbeat")
            self.state.enqueue_data(self.stream_id, payload)
            return True
        except Exception:
            self.close()
            return False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.state.enqueue_close(self.stream_id)
