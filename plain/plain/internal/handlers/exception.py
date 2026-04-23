"""Framework default error renderer.

Called for pre-view failures (URL resolution, middleware) and for view
exceptions that escape `View.handle_exception`. Maps the exception to a
status code, tries `{status}.html`, and falls back to a plain-text body
if the template is missing or rendering itself raises.

Logging is delegated to `plain.logs.log_exception`, which is idempotent
— view-origin exceptions were already logged inside `View.get_response`,
and this call is a no-op for them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from plain.http import HTTPException, Response
from plain.logs import get_framework_logger, log_exception
from plain.runtime import settings
from plain.templates import Template, TemplateFileMissing

if TYPE_CHECKING:
    from plain.http import Request


request_logger = get_framework_logger("plain.request")


def response_for_exception(request: Request, exc: Exception) -> Response:
    log_exception(request, exc)

    status = exc.status_code if isinstance(exc, HTTPException) else 500

    try:
        body = Template(f"{status}.html").render(
            {
                "request": request,
                "status_code": status,
                "exception": exc,
                "DEBUG": settings.DEBUG,
            }
        )
        response = Response(body, status_code=status)
    except TemplateFileMissing:
        response = Response(
            status_code=status, content_type="text/plain; charset=utf-8"
        )
        response.content = f"{status} {response.reason_phrase}"
    except Exception as render_exc:
        if settings.DEBUG:
            raise
        request_logger.error(
            "Error template render failed",
            extra={"path": request.path, "status_code": status, "request": request},
            exc_info=render_exc,
        )
        response = Response(status_code=status)

    if status >= 500:
        # Attach the original exception so observability tooling
        # (Sentry, OTel span recorders) can upload it from the response.
        response.exception = exc
    return response
