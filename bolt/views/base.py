import logging

from bolt.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseNotAllowed,
    JsonResponse,
)
from bolt.utils.decorators import classonlymethod

from .exceptions import HttpResponseException

logger = logging.getLogger("bolt.request")


class View:
    http_method_names = [
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
            return v.get_response()

        # Copy possible attributes set by decorators, e.g. @csrf_exempt, from
        # the dispatch method.
        view.__dict__.update(cls.get_response.__dict__)
        view.view_class = cls

        return view

    def get_request_handler(self) -> callable:
        """Return the handler for the current request method."""

        if not self.request.method:
            raise AttributeError("HTTP method is not set")

        if self.request.method.lower() not in self.http_method_names:
            return self._http_method_not_allowed()

        handler = getattr(
            self, self.request.method.lower(), self._http_method_not_allowed
        )

        return handler

    def get_response(self) -> HttpResponseBase:
        handler = self.get_request_handler()

        try:
            result = handler()
        except HttpResponseException as e:
            return e.response

        if isinstance(result, HttpResponseBase):
            return result

        # Allow return of an int (status code)
        # or tuple (status code, content)?

        if isinstance(result, str):
            return HttpResponse(result)

        if isinstance(result, list):
            return JsonResponse(result, safe=False)

        if isinstance(result, dict):
            return JsonResponse(result)

        raise ValueError(f"Unexpected view return type: {type(result)}")

    def _http_method_not_allowed(self) -> HttpResponse:
        logger.warning(
            "Method Not Allowed (%s): %s",
            self.request.method,
            self.request.path,
            extra={"status_code": 405, "request": self.request},
        )
        return HttpResponseNotAllowed(self._allowed_methods())

    def options(self) -> HttpResponse:
        """Handle responding to requests for the OPTIONS HTTP verb."""
        response = HttpResponse()
        response.headers["Allow"] = ", ".join(self._allowed_methods())
        response.headers["Content-Length"] = "0"
        return response

    def _allowed_methods(self) -> list[str]:
        return [m.upper() for m in self.http_method_names if hasattr(self, m)]
