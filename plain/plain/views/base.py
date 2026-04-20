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
from plain.logs import get_framework_logger, log_exception

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
        self.request = request
        self.url_kwargs = url_kwargs or {}

    def get_request_handler(self) -> Callable[[], Any] | None:
        """Return the handler for the current request method.

        HEAD falls back to `get` when no explicit `head` handler is defined,
        per HTTP semantics (HEAD == GET without a response body). The body
        is stripped at the transport layer, not here.
        """

        if not self.request.method:
            raise AttributeError("HTTP method is not set")

        if self.request.method not in HTTPMethod.__members__:
            return None

        handler = getattr(self, self.request.method.lower(), None)
        if handler is None and self.request.method == "HEAD":
            handler = getattr(self, "get", None)
        return handler

    def before_request(self) -> None:
        """Pre-dispatch hook. Raise to reject the request."""

    def after_response(self, response: ResponseBase) -> ResponseBase:
        """Post-dispatch hook. Runs for every response — successes, errors, 405s.

        Return the response (possibly mutated or replaced). Exceptions
        raised here escape to the framework error renderer — they are
        not routed through `handle_exception`.
        """
        return response

    def handle_exception(self, exc: Exception) -> ResponseBase:
        """Translate a raised exception into a response. Re-raise to defer to the framework default."""
        raise exc

    def get_response(self) -> ResponseBase:
        try:
            self.before_request()

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
                response: ResponseBase = NotAllowedResponse(self._allowed_methods())
            elif inspect.iscoroutinefunction(handler):
                return self._dispatch_handler_async(handler)  # ty: ignore[invalid-return-type]
            else:
                response = self.convert_value_to_response(handler())
        except Exception as e:
            response = self._respond_to_exception(e)
        return self.after_response(response)

    async def _dispatch_handler_async(self, handler: Callable[[], Any]) -> ResponseBase:
        try:
            result = await handler()
            response = self.convert_value_to_response(result)
        except Exception as e:
            response = self._respond_to_exception(e)
        return self.after_response(response)

    def _respond_to_exception(self, exc: Exception) -> ResponseBase:
        if isinstance(exc, ResponseException):
            return exc.response
        log_exception(self.request, exc)
        return self.handle_exception(exc)

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
        methods = [m.upper() for m in HTTPMethod if hasattr(self, m.lower())]
        if "GET" in methods and "HEAD" not in methods:
            methods.append("HEAD")
        return methods
