from __future__ import annotations

import logging
from collections.abc import Callable
from http import HTTPMethod
from typing import Any, Self

from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes.code_attributes import (
    CODE_FUNCTION_NAME,
    CODE_NAMESPACE,
)

from plain.http import (
    JsonResponse,
    NotAllowedResponse,
    NotFoundError404,
    Request,
    Response,
    ResponseBase,
)
from plain.utils.decorators import classonlymethod

from .exceptions import ResponseException

logger = logging.getLogger("plain.request")


tracer = trace.get_tracer("plain")


class View:
    request: Request
    url_args: tuple[Any, ...]
    url_kwargs: dict[str, Any]

    # View.as_view(example="foo") usage can be customized by defining your own __init__ method.
    # def __init__(self, *args, **kwargs):

    def setup(self, request: Request, *url_args: object, **url_kwargs: object) -> None:
        if hasattr(self, "get") and not hasattr(self, "head"):
            self.head = self.get

        self.request = request
        self.url_args = url_args
        self.url_kwargs = url_kwargs

    @classonlymethod
    def as_view(
        cls: type[Self], *init_args: object, **init_kwargs: object
    ) -> Callable[[Request, Any, Any], ResponseBase]:
        def view(
            request: Request, *url_args: object, **url_kwargs: object
        ) -> ResponseBase:
            with tracer.start_as_current_span(
                f"{cls.__name__}",
                kind=trace.SpanKind.INTERNAL,
                attributes={
                    CODE_FUNCTION_NAME: "as_view",
                    CODE_NAMESPACE: f"{cls.__module__}.{cls.__qualname__}",
                },
            ) as span:
                v = cls(*init_args, **init_kwargs)
                v.setup(request, *url_args, **url_kwargs)
                response = v.get_response()
                span.set_status(
                    trace.StatusCode.OK
                    if response.status_code < 400
                    else trace.StatusCode.ERROR
                )
                return response

        view.view_class = cls  # type: ignore[attr-defined]

        return view

    def get_request_handler(self) -> Callable[[], Any] | None:
        """Return the handler for the current request method."""

        if not self.request.method:
            raise AttributeError("HTTP method is not set")

        return getattr(self, self.request.method.lower(), None)

    def get_response(self) -> ResponseBase:
        handler = self.get_request_handler()

        if not handler:
            logger.warning(
                "Method Not Allowed (%s): %s",
                self.request.method,
                self.request.path,
                extra={"status_code": 405, "request": self.request},
            )
            return NotAllowedResponse(self._allowed_methods())

        try:
            result: Any = handler()
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
