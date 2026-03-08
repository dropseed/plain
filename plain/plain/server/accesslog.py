from __future__ import annotations

import datetime
import logging
import traceback
from typing import Any

# Module-level loggers
log = logging.getLogger("plain.server")
access_log = logging.getLogger("plain.server.access")

# Maps field names that come from request headers
_HEADER_FIELDS = {
    "user_agent": "USER-AGENT",
    "referer": "REFERER",
}


def _get_header(req: Any, header_name: str) -> str:
    """Look up a header value from the request's header list."""
    for name, value in req.headers:
        if name == header_name:
            return value
    return ""


def _build_context(
    req: Any,
    *,
    status: int | None = None,
    request_time: datetime.timedelta | None = None,
    resp: Any = None,
) -> dict[str, Any]:
    """Build a context dict from SERVER_ACCESS_LOG_FIELDS."""
    from plain.runtime import settings

    context: dict[str, Any] = {}

    for field in settings.SERVER_ACCESS_LOG_FIELDS:
        if field == "method":
            context["method"] = req.method
        elif field == "path":
            context["path"] = req.path
        elif field == "status":
            if status is not None:
                context["status"] = status
        elif field == "duration_ms":
            if request_time is not None:
                context["duration_ms"] = int(request_time.total_seconds() * 1000)
        elif field == "size":
            if resp is not None:
                context["size"] = getattr(resp, "sent", None) or 0
        elif field == "ip":
            if isinstance(req.peer_addr, tuple):
                context["ip"] = req.peer_addr[0]
            elif isinstance(req.peer_addr, str):
                context["ip"] = req.peer_addr
            else:
                context["ip"] = ""
        elif field == "url":
            if req.query:
                context["url"] = f"{req.path}?{req.query}"
            else:
                context["url"] = req.path
        elif field == "query":
            context["query"] = req.query or ""
        elif field == "protocol":
            context["protocol"] = f"HTTP/{req.version[0]}.{req.version[1]}"
        elif header_name := _HEADER_FIELDS.get(field):
            context[field] = _get_header(req, header_name)

    return context


def log_access(
    resp: Any,
    req: Any,
    request_time: datetime.timedelta,
) -> None:
    """Log an access entry for a completed request."""
    if not access_log.handlers or not access_log.isEnabledFor(logging.INFO):
        return

    raw_status = resp.status
    if isinstance(raw_status, str):
        raw_status = raw_status.split(None, 1)[0]
    status_int = int(raw_status) if raw_status is not None else 0

    context = _build_context(
        req, status=status_int, request_time=request_time, resp=resp
    )

    try:
        access_log.info("Request", extra={"context": context})
    except Exception:
        log.error(traceback.format_exc())


def log_websocket(
    req: Any,
    event: str,
    *,
    request_time: datetime.timedelta | None = None,
) -> None:
    """Log a WebSocket lifecycle event (connect or disconnect)."""
    if not access_log.handlers or not access_log.isEnabledFor(logging.INFO):
        return

    context: dict[str, Any] = {"event": event}
    context.update(
        _build_context(
            req,
            status=101 if event == "connect" else None,
            request_time=request_time,
        )
    )

    try:
        access_log.info("WebSocket", extra={"context": context})
    except Exception:
        log.error(traceback.format_exc())
