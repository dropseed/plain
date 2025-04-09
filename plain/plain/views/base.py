import logging

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
            v = cls(*init_args, **init_kwargs)
            v.setup(request, *url_args, **url_kwargs)
            return v.get_response()

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

        if isinstance(result, ResponseBase):
            return result

        if isinstance(result, str):
            # Assume the str is rendered HTML
            return Response(result)

        if isinstance(result, list):
            return JsonResponse(result, safe=False)

        if isinstance(result, dict):
            return JsonResponse(result)

        if isinstance(result, int):
            return Response(status_code=result)

        if result is None:
            return ResponseNotFound()

        raise ValueError(f"Unexpected view return type: {type(result)}")

    def options(self) -> Response:
        """Handle responding to requests for the OPTIONS HTTP verb."""
        response = Response()
        response.headers["Allow"] = ", ".join(self._allowed_methods())
        response.headers["Content-Length"] = "0"
        return response

    def _allowed_methods(self) -> list[str]:
        known_http_methods = [
            "get",
            "post",
            "put",
            "patch",
            "delete",
            "head",
            "options",
            "trace",
        ]
        return [m.upper() for m in known_http_methods if hasattr(self, m)]
