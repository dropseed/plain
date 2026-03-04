from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import datetime
import logging
import sys
import traceback
from typing import Any

from plain.logs.formatters import KeyValueFormatter

# Module-level loggers
log = logging.getLogger("plain.server")
access_log = logging.getLogger("plain.server.access")

# Maps field names that come from request headers
_HEADER_FIELDS = {
    "user_agent": "USER-AGENT",
    "referer": "REFERER",
}


def setup_bootstrap_logging(accesslog: bool) -> None:
    """Set up minimal logging before fork.

    Provides basic stderr/stdout handlers so the arbiter can log
    before the full plain.logs configuration runs in worker processes.
    """
    log.setLevel(logging.INFO)
    log.propagate = False
    access_log.setLevel(logging.INFO)
    access_log.propagate = False

    # Error log always goes to stderr
    _set_handler(
        log,
        logging.Formatter(
            r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
            r"[%Y-%m-%d %H:%M:%S %z]",
        ),
    )

    # Access log goes to stdout when enabled
    if accesslog:
        _set_handler(
            access_log,
            KeyValueFormatter("[%(levelname)s] %(message)s %(keyvalue)s"),
            stream=sys.stdout,
        )


def _set_handler(
    logger: logging.Logger,
    fmt: logging.Formatter,
    stream: Any = None,
) -> None:
    """Replace any existing plain server handler on the logger."""
    for h in logger.handlers[:]:
        if getattr(h, "_plain_server", False):
            logger.handlers.remove(h)

    h = logging.StreamHandler(stream)
    h.setFormatter(fmt)
    h._plain_server = True  # type: ignore[attr-defined]
    logger.addHandler(h)


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
        access_log.info("Request", extra={"context": context})
    except Exception:
        log.error(traceback.format_exc())
