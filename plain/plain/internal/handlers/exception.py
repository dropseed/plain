from __future__ import annotations

import logging
from functools import wraps
from typing import TYPE_CHECKING

from plain import signals
from plain.exceptions import (
    BadRequest,
    PermissionDenied,
    RequestDataTooBig,
    SuspiciousOperation,
    TooManyFieldsSent,
    TooManyFilesSent,
)
from plain.http import Http404, ResponseServerError
from plain.http.multipartparser import MultiPartParserError
from plain.logs.utils import log_response
from plain.runtime import settings
from plain.views.errors import ErrorView

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.http import Request, Response


def convert_exception_to_response(
    get_response: Callable[[Request], Response],
) -> Callable[[Request], Response]:
    """
    Wrap the given get_response callable in exception-to-response conversion.

    All exceptions will be converted. All known 4xx exceptions (Http404,
    PermissionDenied, MultiPartParserError, SuspiciousOperation) will be
    converted to the appropriate response, and all other exceptions will be
    converted to 500 responses.

    This decorator is automatically applied to all middleware to ensure that
    no middleware leaks an exception and that the next middleware in the stack
    can rely on getting a response instead of an exception.
    """

    @wraps(get_response)
    def inner(request: Request) -> Response:
        try:
            response = get_response(request)
        except Exception as exc:
            response = response_for_exception(request, exc)
        return response

    return inner


def response_for_exception(request: Request, exc: Exception) -> Response:
    if isinstance(exc, Http404):
        response = get_exception_response(
            request=request, status_code=404, exception=None
        )

    elif isinstance(exc, PermissionDenied):
        response = get_exception_response(
            request=request, status_code=403, exception=exc
        )
        log_response(
            "Forbidden (Permission denied): %s",
            request.path,
            response=response,
            request=request,
            exception=exc,
        )

    elif isinstance(exc, MultiPartParserError):
        response = get_exception_response(
            request=request, status_code=400, exception=None
        )
        log_response(
            "Bad request (Unable to parse request body): %s",
            request.path,
            response=response,
            request=request,
            exception=exc,
        )

    elif isinstance(exc, BadRequest):
        response = get_exception_response(
            request=request, status_code=400, exception=exc
        )
        log_response(
            "%s: %s",
            str(exc),
            request.path,
            response=response,
            request=request,
            exception=exc,
        )
    elif isinstance(exc, SuspiciousOperation):
        if isinstance(exc, RequestDataTooBig | TooManyFieldsSent | TooManyFilesSent):
            # POST data can't be accessed again, otherwise the original
            # exception would be raised.
            request._mark_post_parse_error()

        # The request logger receives events for any problematic request
        # The security logger receives events for all SuspiciousOperations
        security_logger = logging.getLogger(f"plain.security.{exc.__class__.__name__}")
        security_logger.error(
            str(exc),
            exc_info=exc,
            extra={"status_code": 400, "request": request},
        )
        response = get_exception_response(
            request=request, status_code=400, exception=None
        )

    else:
        signals.got_request_exception.send(sender=None, request=request)
        response = get_exception_response(
            request=request, status_code=500, exception=None
        )
        log_response(
            "%s: %s",
            response.reason_phrase,
            request.path,
            response=response,
            request=request,
            exception=exc,
        )

    return response


def get_exception_response(
    *, request: Request, status_code: int, exception: Exception | None
) -> Response:
    try:
        view_class = ErrorView.as_view(status_code=status_code, exception=exception)
        return view_class(request)
    except Exception:
        signals.got_request_exception.send(sender=None, request=request)

        # In development mode, re-raise the exception to get a full stack trace
        if settings.DEBUG:
            raise

        # If we can't load the view, return a 500 response
        return ResponseServerError()
