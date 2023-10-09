import logging
import sys
from functools import wraps

from bolt import signals
from bolt.exceptions import (
    BadRequest,
    PermissionDenied,
    RequestDataTooBig,
    SuspiciousOperation,
    TooManyFieldsSent,
    TooManyFilesSent,
)
from bolt.http import Http404
from bolt.http.multipartparser import MultiPartParserError
from bolt.runtime import settings
from bolt.urls import get_resolver, get_urlconf
from bolt.utils.log import log_response
from bolt.views.errors import ErrorView


def convert_exception_to_response(get_response):
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
    def inner(request):
        try:
            response = get_response(request)
        except Exception as exc:
            response = response_for_exception(request, exc)
        return response

    return inner


def response_for_exception(request, exc):
    if isinstance(exc, Http404):
        response = get_exception_response(
            request, get_resolver(get_urlconf()), 404, exc
        )

    elif isinstance(exc, PermissionDenied):
        response = get_exception_response(
            request, get_resolver(get_urlconf()), 403, exc
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
            request, get_resolver(get_urlconf()), 400, exc
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
            request, get_resolver(get_urlconf()), 400, exc
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
        security_logger = logging.getLogger("bolt.security.%s" % exc.__class__.__name__)
        security_logger.error(
            str(exc),
            exc_info=exc,
            extra={"status_code": 400, "request": request},
        )
        response = get_exception_response(
            request, get_resolver(get_urlconf()), 400, exc
        )

    else:
        signals.got_request_exception.send(sender=None, request=request)
        response = handle_uncaught_exception(
            request, get_resolver(get_urlconf()), sys.exc_info()
        )
        log_response(
            "%s: %s",
            response.reason_phrase,
            request.path,
            response=response,
            request=request,
            exception=exc,
        )

    # Force a TemplateResponse to be rendered.
    if not getattr(response, "is_rendered", True) and callable(
        getattr(response, "render", None)
    ):
        response = response.render()

    return response


def get_exception_response(request, resolver, status_code, exception):
    try:
        response = get_error_view(status_code)(request)
    except Exception:
        signals.got_request_exception.send(sender=None, request=request)
        response = handle_uncaught_exception(request, resolver, sys.exc_info())

    return response


def handle_uncaught_exception(request, resolver, exc_info):
    """
    Processing for any otherwise uncaught exceptions (those that will
    generate HTTP 500 responses).
    """
    return get_error_view(500)(request)


def get_error_view(status_code):
    views_by_status = settings.HTTP_ERROR_VIEWS
    if status_code in views_by_status:
        return views_by_status[status_code].as_view()

    # Create a standard view for any other status code
    return ErrorView.as_view(status_code=status_code)
