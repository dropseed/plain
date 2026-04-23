from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from plain.http import (
    NotAllowedResponse,
    Request,
    Response,
    ResponseBase,
)
from plain.logs import get_framework_logger

from .exceptions import ResponseException

logger = get_framework_logger("plain.request")


# TRACE is an XST-adjacent debugging verb, CONNECT is a proxy concept —
# neither belongs in an application view. OPTIONS is provided by the base
# directly; HEAD falls back to GET at dispatch time.
_HANDLER_NAMES = ("get", "post", "put", "patch", "delete", "head")


class View:
    request: Request
    url_kwargs: dict[str, Any]

    implemented_methods: ClassVar[frozenset[str]] = frozenset()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.implemented_methods = frozenset(
            name
            for name in _HANDLER_NAMES
            if getattr(cls, name, None) is not getattr(View, name, None)
        )

    def get(self) -> ResponseBase:
        raise NotImplementedError

    def post(self) -> ResponseBase:
        raise NotImplementedError

    def put(self) -> ResponseBase:
        raise NotImplementedError

    def patch(self) -> ResponseBase:
        raise NotImplementedError

    def delete(self) -> ResponseBase:
        raise NotImplementedError

    def head(self) -> ResponseBase:
        raise NotImplementedError

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

        if self.request.method == "OPTIONS":
            return self.options

        name = self.request.method.lower()
        if name in self.implemented_methods:
            return getattr(self, name)

        if self.request.method == "HEAD" and "get" in self.implemented_methods:
            return self.get

        return None

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
        """Translate a raised exception into a response. Re-raise to defer to the framework default.

        Returning a response suppresses logging — the view has chosen to
        map this exception to a handled outcome (e.g. ValidationError →
        400). Re-raising escapes to the framework error renderer, which
        logs via `log_exception` and renders `{status}.html`. Views that
        want to log a handled branch (e.g. a self-mapped 500) must call
        `log_exception(self.request, exc)` explicitly.
        """
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

    async def _dispatch_handler_async(
        self, handler: Callable[[], Awaitable[ResponseBase]]
    ) -> ResponseBase:
        try:
            result = await handler()
            response = self.convert_value_to_response(result)
        except Exception as e:
            response = self._respond_to_exception(e)
        return self.after_response(response)

    def _respond_to_exception(self, exc: Exception) -> ResponseBase:
        if isinstance(exc, ResponseException):
            return exc.response
        return self.handle_exception(exc)

    def convert_value_to_response(self, value: Any) -> ResponseBase:
        """Hook for subclasses (e.g. `APIView`) to accept shorthand return types."""
        if isinstance(value, ResponseBase):
            return value

        raise TypeError(
            f"{type(self).__name__} handlers must return a Response "
            f"(got {type(value).__name__}). "
            "Wrap raw data in a Response/JsonResponse, or use APIView for "
            "dict/list/tuple shorthand returns."
        )

    def options(self) -> Response:
        """Handle responding to requests for the OPTIONS HTTP verb."""
        response = Response()
        response.headers["Allow"] = ", ".join(self._allowed_methods())
        response.headers["Content-Length"] = "0"
        return response

    def _allowed_methods(self) -> list[str]:
        methods = {m.upper() for m in self.implemented_methods}
        if "GET" in methods:
            methods.add("HEAD")
        methods.add("OPTIONS")
        return sorted(methods)
