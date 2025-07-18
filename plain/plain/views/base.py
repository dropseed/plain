import logging
from http import HTTPMethod

from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes.code_attributes import (
    CODE_FUNCTION_NAME,
    CODE_NAMESPACE,
)

from plain.http import (
    HttpRequest,
    JsonResponse,
    Response,
    ResponseBase,
    ResponseNotAllowed,
    ResponseNotFound,
)
from plain.utils.decorators import classonlymethod

from .exceptions import ResponseException

logger = logging.getLogger("plain.request")


tracer = trace.get_tracer("plain")


class View:
    request: HttpRequest
    url_args: tuple
    url_kwargs: dict

    # View.as_view(example="foo") usage can be customized by defining your own __init__ method.
    # def __init__(self, *args, **kwargs):

    def setup(self, request: HttpRequest, *url_args, **url_kwargs) -> None:
        if hasattr(self, "get") and not hasattr(self, "head"):
            self.head = self.get

        self.request = request
        self.url_args = url_args
        self.url_kwargs = url_kwargs

    @classonlymethod
    def as_view(cls, *init_args, **init_kwargs):
        def view(request, *url_args, **url_kwargs):
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

        view.view_class = cls

        return view

    def get_request_handler(self) -> callable:
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
            return ResponseNotAllowed(self._allowed_methods())

        try:
            result = handler()
        except ResponseException as e:
            return e.response

        return self.convert_value_to_response(result)

    def convert_value_to_response(self, value) -> ResponseBase:
        """Convert a return value to a Response."""
        if isinstance(value, ResponseBase):
            return value

        if isinstance(value, int):
            return Response(status_code=value)

        if value is None:
            # TODO raise 404 instead?
            return ResponseNotFound()

        status_code = 200

        if isinstance(value, tuple):
            if len(value) != 2:
                raise ValueError(
                    "Tuple response must be of length 2 (status_code, value)"
                )

            status_code = value[0]
            value = value[1]

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
