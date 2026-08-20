"""Framework default error renderer — maps exception to status code,
returns a plain-text body. Logging via `log_exception` (idempotent)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HTTPException, Response
from plain.http.response import status_omits_body
from plain.logs import log_exception

if TYPE_CHECKING:
    from plain.http import Request


def response_for_exception(request: Request, exc: Exception) -> Response:
    log_exception(request, exc)

    status = exc.status_code if isinstance(exc, HTTPException) else 500

    if not 200 <= status <= 599:
        # A broken HTTPException subclass (e.g. a 1xx status_code) must
        # not crash the last-resort renderer — Response construction
        # would refuse it. Degrade to a 500 carrying the exception.
        status = 500

    if status_omits_body(status):
        # Headers only — the constructor skips Content-Type for these.
        return Response(status_code=status)

    response = Response(status_code=status, content_type="text/plain; charset=utf-8")
    response.content = f"{status} {response.reason_phrase}"
    if status >= 500:
        response.exception = exc
    return response
