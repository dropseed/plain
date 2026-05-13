"""Framework default error renderer — maps exception to status code,
returns a plain-text body. Logging via `log_exception` (idempotent)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HTTPException, Response
from plain.logs import log_exception

if TYPE_CHECKING:
    from plain.http import Request


def response_for_exception(request: Request, exc: Exception) -> Response:
    log_exception(request, exc)

    status = exc.status_code if isinstance(exc, HTTPException) else 500

    response = Response(status_code=status, content_type="text/plain; charset=utf-8")
    response.content = f"{status} {response.reason_phrase}"
    if status >= 500:
        response.exception = exc
    return response
