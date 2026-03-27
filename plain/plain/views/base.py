from __future__ import annotations

import inspect
from collections.abc import Callable
from http import HTTPMethod
from typing import TYPE_CHECKING, Any

from plain.http import (
    JsonResponse,
    NotAllowedResponse,
    NotFoundError404,
    Request,
    Response,
    ResponseBase,
)
from plain.logs import get_framework_logger

from .exceptions import ResponseException

logger = get_framework_logger("plain.request")


class View:
    request: Request
    url_kwargs: dict[str, Any]

    if TYPE_CHECKING:

        def get(self) -> Any: ...
        def post(self) -> Any: ...
        def put(self) -> Any: ...
        def patch(self) -> Any: ...
        def delete(self) -> Any: ...
        def head(self) -> Any: ...
        def trace(self) -> Any: ...

    def __init__(
        self,
        *,
        request: Request,
        url_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if hasattr(self, "get") and not hasattr(self, "head"):
            self.head = self.get

        self.request = request
        self.url_kwargs = url_kwargs or {}

    def get_request_handler(self) -> Callable[[], Any] | None:
        """Return the handler for the current request method."""

        if not self.request.method:
            raise AttributeError("HTTP method is not set")

        return getattr(self, self.request.method.lower(), None)

    def get_response(self) -> ResponseBase:
        handler = self.get_request_handler()

        if not handler:
            logger.warning(
                "Method not allowed",
                extra={
                    "method": self.request.method,
                    "path": self.request.path,
                    "status_code": 405,
                    "request": self.request,
                },
            )
            return NotAllowedResponse(self._allowed_methods())

        if inspect.iscoroutinefunction(handler):
            return self._dispatch_handler_async(handler)  # type: ignore[return-value]

        try:
            result: Any = handler()
        except ResponseException as e:
            return e.response

        return self.convert_value_to_response(result)

    async def _dispatch_handler_async(self, handler: Callable[[], Any]) -> ResponseBase:
        try:
            result = await handler()
        except ResponseException as e:
            return e.response

        return self.convert_value_to_response(result)

    def convert_value_to_response(self, value: Any) -> ResponseBase:
        """Convert a return value to a Response."""
        if isinstance(value, ResponseBase):
            return value

        if isinstance(value, int):
            return Response(status_code=value)

        if value is None:
            raise NotFoundError404

        status_code = 200

        if isinstance(value, tuple):
            if len(value) != 2:
                raise ValueError(
                    "Tuple response must be of length 2 (status_code, value)"
                )

            status_code: int = value[0]
            value: Any = value[1]

        if isinstance(value, str):
            return Response(value, status_code=status_code)

        if isinstance(value, list):
            return JsonResponse(value, status_code=status_code, safe=False)

        if isinstance(value, dict):
            return JsonResponse(value, status_code=status_code)

        raise ValueError(f"Unexpected view return type: {type(value)}")

    def options(self) -> Response:
        """Handle responding to requests for the OPTIONS HTTP verb."""
        response = Response()
        response.headers["Allow"] = ", ".join(self._allowed_methods())
        response.headers["Content-Length"] = "0"
        return response

    def _allowed_methods(self) -> list[str]:
        return [m.upper() for m in HTTPMethod if hasattr(self, m.lower())]
