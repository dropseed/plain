"""Server-Sent Events (SSE) protocol implementation."""

from __future__ import annotations

import json
from typing import Any


def format_sse_event(
    data: Any,
    event: str | None = None,
    event_id: str | None = None,
    retry: int | None = None,
) -> bytes:
    """Format data as an SSE event.

    SSE format:
        event: <event type>\n
        id: <event id>\n
        retry: <reconnection time ms>\n
        data: <data line 1>\n
        data: <data line 2>\n
        \n
    """
    lines: list[str] = []

    if event is not None:
        lines.append(f"event: {event}")

    if event_id is not None:
        lines.append(f"id: {event_id}")

    if retry is not None:
        lines.append(f"retry: {retry}")

    # Serialize data
    if isinstance(data, dict | list):
        data_str = json.dumps(data)
    elif data is None:
        data_str = ""
    else:
        data_str = str(data)

    # Each line of data gets its own "data: " prefix
    for line in data_str.split("\n"):
        lines.append(f"data: {line}")

    # Events are terminated by a blank line
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def format_sse_comment(comment: str = "") -> bytes:
    """Format an SSE comment (used as heartbeat).

    Comments start with a colon and are ignored by EventSource.
    """
    return f": {comment}\n\n".encode()


SSE_HEADERS = [
    ("Content-Type", "text/event-stream"),
    ("Cache-Control", "no-cache"),
    ("Connection", "keep-alive"),
    ("X-Accel-Buffering", "no"),  # Disable nginx buffering
]
