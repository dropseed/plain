"""Request-exception logging.

`log_exception` is the single logging entry point for exceptions raised
during request handling. Called from `View.get_response` for exceptions
that reach `handle_exception`, and from the framework's
`response_for_exception` for pre-view failures (URL resolution,
middleware). The sentinel attribute makes it idempotent, so an exception
caught at multiple layers is logged once.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .logger import get_framework_logger

if TYPE_CHECKING:
    from plain.http import Request


request_logger = get_framework_logger("plain.request")

_LOGGED_SENTINEL = "_plain_logged"


def log_exception(request: Request, exc: Exception) -> None:
    """Log an exception raised during request handling.

    Idempotent — setting a sentinel on the exception means multiple call
    sites won't double-log. 404s are skipped unconditionally since
    crawler/probe noise drowns real signal.
    """
    # Deferred to avoid a circular import: plain.logs is loaded during
    # plain.runtime bootstrap, which happens before plain.http is ready.
    from plain.http.exceptions import (
        HTTPException,
        NotFoundError404,
        SuspiciousOperationError400,
    )

    if getattr(exc, _LOGGED_SENTINEL, False):
        return
    setattr(exc, _LOGGED_SENTINEL, True)

    if isinstance(exc, NotFoundError404):
        return

    base = {"path": request.path, "request": request}

    if isinstance(exc, SuspiciousOperationError400):
        security_logger = logging.getLogger(f"plain.security.{type(exc).__name__}")
        security_logger.error(str(exc), extra=base, exc_info=exc)
        return

    if isinstance(exc, HTTPException):
        request_logger.warning(
            "HTTP error",
            extra={**base, "error": str(exc), "status_code": exc.status_code},
        )
        return

    request_logger.error("Server error", extra=base, exc_info=exc)
