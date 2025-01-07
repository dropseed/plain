import logging

from plain.http import (
    HttpRequest,
    JsonResponse,
    Response,
    ResponseBase,
    ResponseNotAllowed,
)
from plain.utils.decorators import classonlymethod

from .exceptions import ResponseException

logger = logging.getLogger("plain.request")


class View:
    request: HttpRequest
    url_args: tuple
    url_kwargs: dict

    # By default, any of these are allowed if a method is defined for it.
    allowed_http_methods = [
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "head",
        "options",
        "trace",
    ]

    def __init__(self, *args, **kwargs) -> None:
        # Views can customize their init, which receives
        # the args and kwargs from as_view()
        pass

    def setup(self, request: HttpRequest, *args, **kwargs) -> None:
        if hasattr(self, "get") and not hasattr(self, "head"):
            self.head = self.get

        self.request = request
        self.url_args = args
        self.url_kwargs = kwargs

    @classonlymethod
    def as_view(cls, *init_args, **init_kwargs):
        def view(request, *args, **kwargs):
            v = cls(*init_args, **init_kwargs)
            v.setup(request, *args, **kwargs)
            try:
                return v.get_response()
            except ResponseException as e:
                return e.response

        view.view_class = cls

        return view

    def get_request_handler(self) -> callable:
        """Return the handler for the current request method."""

        if not self.request.method:
            raise AttributeError("HTTP method is not set")

        handler = getattr(self, self.request.method.lower(), None)

        if not handler or self.request.method.lower() not in self.allowed_http_methods:
            logger.warning(
                "Method Not Allowed (%s): %s",
                self.request.method,
                self.request.path,
                extra={"status_code": 405, "request": self.request},
            )
            raise ResponseException(ResponseNotAllowed(self._allowed_methods()))

        return handler

    def get_response(self) -> ResponseBase:
        handler = self.get_request_handler()

        result = handler()

        if isinstance(result, ResponseBase):
            return result

        if isinstance(result, str):
            return Response(result)

        if isinstance(result, list):
            return JsonResponse(result, safe=False)

        if isinstance(result, dict):
            return JsonResponse(result)

        if isinstance(result, int):
            return Response(status=result)

        # Allow tuple for (status_code, content)?

        raise ValueError(f"Unexpected view return type: {type(result)}")

    def options(self) -> Response:
        """Handle responding to requests for the OPTIONS HTTP verb."""
        response = Response()
        response.headers["Allow"] = ", ".join(self._allowed_methods())
        response.headers["Content-Length"] = "0"
        return response

    def _allowed_methods(self) -> list[str]:
        return [m.upper() for m in self.allowed_http_methods if hasattr(self, m)]
