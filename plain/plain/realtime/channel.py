from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any

from plain.http import AsyncStreamingResponse, ForbiddenError403
from plain.views import View

from .sse import format_sse_comment, format_sse_event

if TYPE_CHECKING:
    from plain.http import Request, ResponseBase


async def pg_listen(
    *channels: str, heartbeat_interval: float = 15.0
) -> AsyncGenerator[tuple[str | None, str], None]:
    """Async generator that yields (channel, payload) from Postgres NOTIFY.

    Also sends periodic SSE heartbeat comments to keep connections alive.
    """
    import psycopg
    import psycopg.sql

    from .listener import _get_connection_string

    conninfo = _get_connection_string()
    conn = await psycopg.AsyncConnection.connect(conninfo, autocommit=True)

    try:
        for channel in channels:
            await conn.execute(
                psycopg.sql.SQL("LISTEN {}").format(psycopg.sql.Identifier(channel))
            )

        while True:
            async for notify in conn.notifies(timeout=heartbeat_interval):
                yield notify.channel, notify.payload or ""
            # Timeout — send heartbeat by yielding None
            yield None, ""
    except (psycopg.OperationalError, asyncio.CancelledError):
        pass
    finally:
        try:
            await conn.close()
        except Exception:
            pass


class Channel(View):
    """View subclass for Server-Sent Events (SSE) via Postgres LISTEN/NOTIFY.

    Register via URL router like any other view::

        # urls.py
        path("events/user/", UserEventsChannel)

    Example::

        class UserEventsChannel(Channel):
            def authorize(self, request):
                return request.user.is_authenticated

            def subscribe(self, request):
                return [f"user:{request.user.pk}"]

            def transform(self, channel_name, payload):
                return {"type": "update", "data": payload}
    """

    view_protocol: str | None = "sse"

    def authorize(self, request: Request) -> bool:
        """Check if the request is allowed to connect to this channel.

        Called in the sync context with full access to the ORM, sessions, etc.
        Return True to allow the connection, False to reject with 403.
        """
        return True

    def subscribe(self, request: Request) -> list[str]:
        """Return the list of Postgres NOTIFY channel names to listen on.

        Called in the sync context after authorize() succeeds.
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
        authorized = await loop.run_in_executor(None, self.authorize, self.request)
        if not authorized:
            raise ForbiddenError403

        subscriptions = await loop.run_in_executor(None, self.subscribe, self.request)
        if not subscriptions:
            raise ForbiddenError403

        async def stream() -> AsyncGenerator[str, None]:
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
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
