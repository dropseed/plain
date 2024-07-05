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

        # Copy possible attributes set by decorators, e.g. @csrf_exempt, from
        # the dispatch method.
        view.__dict__.update(cls.get_response.__dict__)
        view.view_class = cls

        return view

    def get_request_handler(self) -> callable:
        """Return the handler for the current request method."""

        if not self.request.method:
            raise AttributeError("HTTP method is not set")

        handler = getattr(self, self.request.method.lower(), None)

        if not handler:
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

        # Allow return of an int (status code)
        # or tuple (status code, content)?

        if isinstance(result, str):
            return Response(result)

        if isinstance(result, list):
            return JsonResponse(result, safe=False)

        if isinstance(result, dict):
            return JsonResponse(result)

        raise ValueError(f"Unexpected view return type: {type(result)}")

    def options(self) -> Response:
        """Handle responding to requests for the OPTIONS HTTP verb."""
        response = Response()
        response.headers["Allow"] = ", ".join(self._allowed_methods())
        response.headers["Content-Length"] = "0"
        return response

    def _allowed_methods(self) -> list[str]:
        known_http_method_names = [
            "get",
            "post",
            "put",
            "patch",
            "delete",
            "head",
            "options",
            "trace",
        ]
        return [m.upper() for m in known_http_method_names if hasattr(self, m)]
