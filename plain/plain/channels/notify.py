"""Send notifications through Postgres NOTIFY.

Usage from views or anywhere in sync code::

    from plain.channels import notify
    notify("user:123", {"comment_id": 42, "text": "Hello"})
"""

from __future__ import annotations

import json
from typing import Any

from plain.models import connection


def notify(channel: str, payload: Any = "") -> None:
    """Send a NOTIFY on a Postgres channel.

    Args:
        channel: The channel name (must match what Channel.subscribe() returns).
        payload: Data to send. Dicts/lists are JSON-serialized. Max 8000 bytes.
    """
    if isinstance(payload, dict | list):
        payload_str = json.dumps(payload)
    else:
        payload_str = str(payload)

    with connection.cursor() as cursor:
        # Use format string for the channel name (it's an identifier, not a value)
        # but parameterize the payload to prevent injection
        cursor.execute("SELECT pg_notify(%s, %s)", [channel, payload_str])
