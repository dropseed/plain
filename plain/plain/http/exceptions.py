"""
HTTP exceptions that map to HTTP status codes.

Raise these (or your own subclasses) from views, middleware, or helpers to
abort with a specific status. The framework reads `status_code` off the
exception and renders the matching error response.
"""

from .response import is_valid_status_code


class HTTPException(Exception):
    """Base class for exceptions that map to HTTP status codes.

    Subclass to define your own:

        class PaymentRequiredError402(HTTPException):
            status_code = 402
    """

    status_code: int = 500

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Catch a bad status at the line that wrote it. Response
        # construction rejects statuses outside this range, so a broken
        # subclass (e.g. a 1xx, a string, or None) would otherwise crash
        # the error renderers at request time instead of failing at
        # import time.
        if not is_valid_status_code(cls.status_code):
            raise ValueError(
                f"{cls.__name__}.status_code must be an integer from "
                f"200 to 599, got {cls.status_code!r}."
            )


class BadRequestError400(HTTPException):
    """The request is malformed and cannot be processed (HTTP 400)"""

    status_code = 400


class ForbiddenError403(HTTPException):
    """The user did not have permission to do that (HTTP 403)"""

    status_code = 403


class NotFoundError404(HTTPException):
    """The requested resource was not found (HTTP 404)"""

    status_code = 404


class UnsupportedMediaTypeError415(HTTPException):
    """The request body is in a media type the server does not parse (HTTP 415)"""

    status_code = 415


class SuspiciousOperationError400(BadRequestError400):
    """The user did something suspicious (HTTP 400)"""


class SuspiciousMultipartFormError400(SuspiciousOperationError400):
    """Suspect MIME request in multipart form data"""


class SuspiciousFileOperationError400(SuspiciousOperationError400):
    """A Suspicious filesystem operation was attempted"""


class TooManyFieldsSentError400(SuspiciousOperationError400):
    """
    The number of fields in a GET or POST request exceeded
    settings.DATA_UPLOAD_MAX_NUMBER_FIELDS.
    """


class TooManyFilesSentError400(SuspiciousOperationError400):
    """
    The number of fields in a GET or POST request exceeded
    settings.DATA_UPLOAD_MAX_NUMBER_FILES.
    """


class ContentTooLargeError413(HTTPException):
    """The request body is larger than the server or app accepts (HTTP 413).

    Raised when a body exceeds settings.SERVER_MAX_REQUEST_BODY_SIZE at the
    server edge, or when the bytes read into memory (excluding file
    uploads) exceed settings.DATA_UPLOAD_MAX_MEMORY_SIZE.
    """

    status_code = 413


def status_for_exception(exc: Exception) -> int:
    """Status code for rendering an exception as an error response.

    An `HTTPException`'s `status_code`, 500 for anything else — clamped
    to what Response construction accepts, so a mutated or nonsense
    status (subclass definitions are validated, instances can be
    poked) can never crash an error renderer.
    """
    status = exc.status_code if isinstance(exc, HTTPException) else 500
    return status if is_valid_status_code(status) else 500
