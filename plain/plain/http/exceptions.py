"""
HTTP exceptions that map to HTTP status codes.

Raise these (or your own subclasses) from views, middleware, or helpers to
abort with a specific status. The framework reads `status_code` off the
exception and renders the matching error response.
"""


class HTTPException(Exception):
    """Base class for exceptions that map to HTTP status codes.

    Subclass to define your own:

        class PaymentRequiredError402(HTTPException):
            status_code = 402
    """

    status_code: int = 500


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
