import logging
from functools import wraps

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
from plain.logs import log_response
from plain.runtime import settings
from plain.utils.module_loading import import_string
from plain.views.errors import ErrorView


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
        response = get_exception_response(request, 404)

    elif isinstance(exc, PermissionDenied):
        response = get_exception_response(request, 403)
        log_response(
            "Forbidden (Permission denied): %s",
            request.path,
            response=response,
            request=request,
            exception=exc,
        )

    elif isinstance(exc, MultiPartParserError):
        response = get_exception_response(request, 400)
        log_response(
            "Bad request (Unable to parse request body): %s",
            request.path,
            response=response,
            request=request,
            exception=exc,
        )

    elif isinstance(exc, BadRequest):
        response = get_exception_response(request, 400)
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
        security_logger = logging.getLogger(
            "plain.security.%s" % exc.__class__.__name__
        )
        security_logger.error(
            str(exc),
            exc_info=exc,
            extra={"status_code": 400, "request": request},
        )
        response = get_exception_response(request, 400)

    else:
        signals.got_request_exception.send(sender=None, request=request)
        response = get_exception_response(request, 500)
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


def get_exception_response(request, status_code):
    try:
        return get_error_view(status_code)(request)
    except Exception:
        signals.got_request_exception.send(sender=None, request=request)
        return handle_uncaught_exception()


def handle_uncaught_exception():
    """
    Processing for any otherwise uncaught exceptions (those that will
    generate HTTP 500 responses).
    """
    return ResponseServerError()


def get_error_view(status_code):
    views_by_status = settings.HTTP_ERROR_VIEWS
    if status_code in views_by_status:
        view = views_by_status[status_code]
        if isinstance(view, str):
            # Import the view if it's a string
            view = import_string(view)
        return view.as_view()

    # Create a standard view for any other status code
    return ErrorView.as_view(status_code=status_code)
