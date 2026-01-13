from __future__ import annotations

import logging
from functools import wraps
from typing import TYPE_CHECKING

from plain.forms.exceptions import FormFieldMissingError
from plain.http import (
    BadRequestError400,
    ForbiddenError403,
    NotFoundError404,
    Response,
    SuspiciousOperationError400,
)
from plain.http.multipartparser import MultiPartParserError
from plain.runtime import settings
from plain.views.errors import ErrorView

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.http import Request, Response, ResponseBase


request_logger = logging.getLogger("plain.request")


def convert_exception_to_response(
    get_response: Callable[[Request], ResponseBase],
) -> Callable[[Request], ResponseBase]:
    """
    Wrap the given get_response callable in exception-to-response conversion.

    All exceptions will be converted. All known 4xx exceptions (NotFoundError404,
    ForbiddenError403, MultiPartParserError, SuspiciousOperationError400) will be
    converted to the appropriate response, and all other exceptions will be
    converted to 500 responses.

    This decorator is automatically applied to all middleware to ensure that
    no middleware leaks an exception and that the next middleware in the stack
    can rely on getting a response instead of an exception.
    """

    @wraps(get_response)
    def inner(request: Request) -> ResponseBase:
        try:
            response = get_response(request)
        except Exception as exc:
            response = response_for_exception(request, exc)
        return response

    return inner


def response_for_exception(request: Request, exc: Exception) -> Response:
    if isinstance(exc, NotFoundError404):
        response = get_exception_response(
            request=request, status_code=404, exception=None
        )

    elif isinstance(exc, ForbiddenError403):
        response = get_exception_response(
            request=request, status_code=403, exception=exc
        )
        request_logger.warning(
            "Forbidden (Permission denied): %s",
            request.path,
            extra={"status_code": response.status_code, "request": request},
            exc_info=exc,
        )

    elif isinstance(exc, MultiPartParserError):
        response = get_exception_response(
            request=request, status_code=400, exception=None
        )
        request_logger.warning(
            "Bad request (Unable to parse request body): %s",
            request.path,
            extra={"status_code": response.status_code, "request": request},
            exc_info=exc,
        )

    elif isinstance(exc, BadRequestError400):
        response = get_exception_response(
            request=request, status_code=400, exception=exc
        )
        request_logger.warning(
            "%s: %s",
            str(exc),
            request.path,
            extra={"status_code": response.status_code, "request": request},
            exc_info=exc,
        )
    elif isinstance(exc, SuspiciousOperationError400):
        # The request logger receives events for any problematic request
        # The security logger receives events for all SuspiciousOperationError400s
        security_logger = logging.getLogger(f"plain.security.{exc.__class__.__name__}")
        security_logger.error(
            str(exc),
            extra={"status_code": 400, "request": request},
            exc_info=exc,
        )
        response = get_exception_response(
            request=request, status_code=400, exception=None
        )

    elif isinstance(exc, FormFieldMissingError):
        response = get_exception_response(
            request=request, status_code=400, exception=None
        )
        request_logger.warning(
            "Bad request (missing form field '%s'): %s",
            exc.field_name,
            request.path,
            extra={"status_code": 400, "request": request},
        )

    else:
        response = get_exception_response(
            request=request, status_code=500, exception=None
        )
        request_logger.error(
            "%s: %s",
            response.reason_phrase,
            request.path,
            extra={"status_code": response.status_code, "request": request},
            exc_info=exc,
        )

    return response


def get_exception_response(
    *, request: Request, status_code: int, exception: Exception | None
) -> Response:
    try:
        view_class = ErrorView.as_view(status_code=status_code, exception=exception)
        response = view_class(request)
        if response.status_code >= 500 and exception is not None:
            # Attach the exception to the response for logging/observability
            response.exception = exception
        return response
    except Exception as e:
        # In development mode, re-raise the exception to get a full stack trace
        if settings.DEBUG:
            raise

        # If we can't load the view, return a 500 response
        response = Response(status_code=500)
        response.exception = e
        return response
