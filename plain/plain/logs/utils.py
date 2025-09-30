from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.http.request import Request
    from plain.http.response import ResponseBase

request_logger = logging.getLogger("plain.request")


def log_response(
    message: str,
    *args: Any,
    response: ResponseBase | None = None,
    request: Request | None = None,
    logger: logging.Logger = request_logger,
    level: str | None = None,
    exception: BaseException | None = None,
) -> None:
    """
    Log errors based on Response status.

    Log 5xx responses as errors and 4xx responses as warnings (unless a level
    is given as a keyword argument). The Response status_code and the
    request are passed to the logger's extra parameter.
    """
    if response is None:
        return

    # Check if the response has already been logged. Multiple requests to log
    # the same response can be received in some cases, e.g., when the
    # response is the result of an exception and is logged when the exception
    # is caught, to record the exception.
    if getattr(response, "_has_been_logged", False):
        return

    if level is None:
        if response.status_code >= 500:
            level = "error"
        elif response.status_code >= 400:
            level = "warning"
        else:
            level = "info"

    getattr(logger, level)(
        message,
        *args,
        extra={
            "status_code": response.status_code,
            "request": request,
        },
        exc_info=exception,
    )
    response._has_been_logged = True  # type: ignore[attr-defined]
