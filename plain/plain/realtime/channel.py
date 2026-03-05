from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from plain.http import AsyncStreamingResponse, ForbiddenError403
from plain.server.protocols.sse import SSE_HEADERS, format_sse_comment, format_sse_event
from plain.views import View

if TYPE_CHECKING:
    from plain.http import ResponseBase


async def pg_listen(
    *channels: str, heartbeat_interval: float = 15.0
) -> AsyncGenerator[tuple[str | None, str], None]:
    """Async generator that yields (channel, payload) from Postgres NOTIFY.

    Uses a shared per-worker Postgres connection instead of one per caller.
    Also sends periodic heartbeats (None, "") to keep connections alive.
    """
    from .listener import SharedListener

    listener = SharedListener.get()
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    await listener.subscribe(queue, *channels)

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                yield item
            except TimeoutError:
                yield None, ""
    except asyncio.CancelledError:
        pass
    finally:
        await listener.unsubscribe(queue, *channels)


class SSEView(View):
    """View subclass for Server-Sent Events (SSE) via Postgres LISTEN/NOTIFY.

    Register via URL router like any other view::

        # urls.py
        path("events/user/", UserEvents)

    Example::

        class UserEvents(SSEView):
            def authorize(self):
                return self.request.user.is_authenticated

            def subscribe(self):
                return [f"user:{self.request.user.pk}"]

            def transform(self, channel_name, payload):
                return {"type": "update", "data": payload}
    """

    view_protocol: str | None = "sse"

    def authorize(self) -> bool:
        """Check if the request is allowed to connect.

        Called in the sync context with full access to the ORM, sessions, etc.
        Return True to allow the connection, False to reject with 403.
        Access the request via self.request.
        """
        return True

    def subscribe(self) -> list[str]:
        """Return the list of Postgres NOTIFY channel names to listen on.

        Called in the sync context after authorize() succeeds.
        Access the request via self.request.
        """
        return []

    def transform(self, channel_name: str, payload: str) -> dict[str, Any] | str | None:
        """Transform a Postgres NOTIFY payload before sending to the client.

        Return a dict (will be JSON-serialized), a string (sent as-is),
        or None to skip sending this event.
        """
        return payload

    async def get(self) -> ResponseBase:
        loop = asyncio.get_running_loop()

        # Run sync authorize/subscribe in executor for ORM access
        authorized = await loop.run_in_executor(None, self.authorize)
        if not authorized:
            raise ForbiddenError403

        subscriptions = await loop.run_in_executor(None, self.subscribe)
        if not subscriptions:
            raise ForbiddenError403

        async def stream() -> AsyncGenerator[bytes, None]:
            async for channel_name, payload in pg_listen(*subscriptions):
                if channel_name is None:
                    # Heartbeat
                    yield format_sse_comment("heartbeat")
                    continue

                # Transform payload
                transformed = await loop.run_in_executor(
                    None, self.transform, channel_name, payload
                )
                if transformed is None:
                    continue

                if isinstance(transformed, dict):
                    data = json.dumps(transformed)
                else:
                    data = str(transformed)

                yield format_sse_event(data, event=channel_name)

        return AsyncStreamingResponse(
            stream(),
            content_type="text/event-stream",
            headers=SSE_HEADERS,
        )
