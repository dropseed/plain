from __future__ import annotations

import datetime
import logging
import sys
import traceback
from typing import Any

from plain.logs import get_framework_logger

# Module-level loggers
log = get_framework_logger()
access_log = get_framework_logger("plain.server.access")

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


def log_access(
    resp: Any,
    req: Any,
    request_time: datetime.timedelta,
) -> None:
    """Log an access entry for a completed request."""
    if not access_log.handlers or not access_log.isEnabledFor(logging.INFO):
        return

    from plain.runtime import settings

    status = resp.status
    if isinstance(status, str):
        status = status.split(None, 1)[0]

    context: dict[str, Any] = {}

    for field in settings.SERVER_ACCESS_LOG_FIELDS:
        if field == "method":
            context["method"] = req.method
        elif field == "path":
            context["path"] = req.path
        elif field == "status":
            context["status"] = int(status)
        elif field == "duration_ms":
            context["duration_ms"] = int(request_time.total_seconds() * 1000)
        elif field == "size":
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

    try:
        access_log.info("Request", extra=context)
    except Exception:
        log.error(traceback.format_exc())


def configure_access_log(*, enabled: bool, log_format: str) -> None:
    """Configure the access logger.

    Always writes to stdout (separate from the LOG_STREAM setting)
    and can be disabled entirely via the enabled flag.
    """
    from plain.logs.configure import create_log_formatter

    access_log.setLevel(logging.INFO)
    access_log.handlers.clear()
    access_log.propagate = False

    if enabled:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(create_log_formatter(log_format))
        access_log.addHandler(handler)
