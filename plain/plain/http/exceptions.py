"""
HTTP exceptions that are converted to HTTP responses by the exception handler.
The suffix indicates the HTTP status code that will be returned.
"""


class NotFoundError404(Exception):
    """The requested resource was not found (HTTP 404)"""

    pass


class ForbiddenError403(Exception):
    """The user did not have permission to do that (HTTP 403)"""

    pass


class BadRequestError400(Exception):
    """The request is malformed and cannot be processed (HTTP 400)"""

    pass


class SuspiciousOperationError400(Exception):
    """The user did something suspicious (HTTP 400)"""


class SuspiciousMultipartFormError400(SuspiciousOperationError400):
    """Suspect MIME request in multipart form data"""

    pass


class SuspiciousFileOperationError400(SuspiciousOperationError400):
    """A Suspicious filesystem operation was attempted"""

    pass


class TooManyFieldsSentError400(SuspiciousOperationError400):
    """
    The number of fields in a GET or POST request exceeded
    settings.DATA_UPLOAD_MAX_NUMBER_FIELDS.
    """

    pass


class TooManyFilesSentError400(SuspiciousOperationError400):
    """
    The number of fields in a GET or POST request exceeded
    settings.DATA_UPLOAD_MAX_NUMBER_FILES.
    """

    pass


class RequestDataTooBigError400(SuspiciousOperationError400):
    """
    The size of the request (excluding any file uploads) exceeded
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE.
    """

    pass
