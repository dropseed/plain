from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.http import Request


class Channel:
    """Base class for server-sent event channels.

    Subclass this to define real-time endpoints. All methods are sync —
    the framework handles async infrastructure internally.

    Example::

        class UserEvents(Channel):
            path = "/events/user/"

            def authorize(self, request):
                return request.user.is_authenticated

            def subscribe(self, request):
                return [f"user:{request.user.pk}"]

            def transform(self, channel_name, payload):
                return {"type": "update", "data": payload}
    """

    # URL path for this channel. Required.
    path: str = ""

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

        Called in the sync context (via threadpool) when a notification arrives.
        Return a dict (will be JSON-serialized), a string (sent as-is),
        or None to skip sending this event.
        """
        return payload
