"""Framework default error renderer — maps exception to status code,
returns a plain-text body. Logging via `log_exception` (idempotent)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import Response, status_for_exception, status_omits_body
from plain.logs import log_exception

if TYPE_CHECKING:
    from plain.http import Request


def response_for_exception(request: Request, exc: Exception) -> Response:
    log_exception(request, exc)

    status = status_for_exception(exc)

    if status_omits_body(status):
        # Headers only — the constructor skips Content-Type for these.
        return Response(status_code=status)

    response = Response(status_code=status, content_type="text/plain; charset=utf-8")
    response.content = f"{status} {response.reason_phrase}"
    if status >= 500:
        response.exception = exc
    return response
