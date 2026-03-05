from __future__ import annotations

import inspect
import types
from typing import TYPE_CHECKING, Any

from opentelemetry import baggage, trace
from opentelemetry.context import Context
from opentelemetry.semconv.attributes import http_attributes, url_attributes

from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings
from plain.urls import get_resolver
from plain.utils.module_loading import import_string

from .exception import convert_exception_to_response

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.http import Request, Response, ResponseBase
    from plain.urls import ResolverMatch


# These middleware classes are always used by Plain.
BUILTIN_BEFORE_MIDDLEWARE = [
    "plain.internal.middleware.healthcheck.HealthcheckMiddleware",  # Respond to healthcheck before anything else
    "plain.internal.middleware.hosts.HostValidationMiddleware",  # Validate Host header first
    "plain.internal.middleware.headers.DefaultHeadersMiddleware",  # Runs after response, to set missing headers
    "plain.internal.middleware.https.HttpsRedirectMiddleware",  # Runs before response, to redirect to HTTPS quickly
    "plain.csrf.middleware.CsrfViewMiddleware",  # Runs before and after get_response...
]

BUILTIN_AFTER_MIDDLEWARE = [
    # Want this to run first (when reversed) so the slash middleware
    # can immediately redirect to the slash-appended path if there is one.
    "plain.internal.middleware.slash.RedirectSlashMiddleware",
]


tracer = trace.get_tracer("plain")


class BaseHandler:
    _middleware_chain: Callable[[Request], ResponseBase] | None = None

    def load_middleware(self) -> None:
        """
        Populate middleware lists from settings.MIDDLEWARE.

        Must be called after the environment is fixed (see __call__ in subclasses).
        """
        handler = convert_exception_to_response(self._get_response)

        middlewares = reversed(
            BUILTIN_BEFORE_MIDDLEWARE + settings.MIDDLEWARE + BUILTIN_AFTER_MIDDLEWARE
        )

        for middleware_path in middlewares:
            middleware = import_string(middleware_path)
            mw_instance = middleware(handler)

            if mw_instance is None:
                raise ImproperlyConfigured(
                    f"Middleware factory {middleware_path} returned None."
                )

            handler = convert_exception_to_response(mw_instance.process_request)

        # We only assign to this when initialization is complete as it is used
        # as a flag for initialization being complete.
        self._middleware_chain = handler

    def _build_request_span(self, request: Request) -> tuple[dict[str, str], Context]:
        """Build span attributes and baggage context for a request."""
        span_attributes: dict[str, str] = {
            "plain.request.id": request.unique_id,
            http_attributes.HTTP_REQUEST_METHOD: request.method or "",
            url_attributes.URL_PATH: request.path_info,
            url_attributes.URL_SCHEME: request.scheme,
        }

        try:
            span_attributes[url_attributes.URL_FULL] = request.build_absolute_uri()
        except (KeyError, AttributeError):
            pass

        if request.query_string:
            span_attributes[url_attributes.URL_QUERY] = request.query_string

        span_context = baggage.set_baggage("http.request.cookies", request.cookies)
        span_context = baggage.set_baggage(
            "http.request.headers", request.headers, span_context
        )

        return span_attributes, span_context

    def _finish_span(self, span: Any, response: ResponseBase) -> None:
        """Set span status and record exceptions from a response."""
        span.set_attribute(
            http_attributes.HTTP_RESPONSE_STATUS_CODE, response.status_code
        )
        span.set_status(
            trace.StatusCode.OK
            if response.status_code < 400
            else trace.StatusCode.ERROR
        )
        if response.exception:
            span.record_exception(response.exception)

    def get_response(self, request: Request) -> ResponseBase:
        """Return a Response object for the given Request."""
        assert self._middleware_chain is not None, (
            "load_middleware() must be called before get_response()"
        )

        span_attributes, span_context = self._build_request_span(request)

        with tracer.start_as_current_span(
            f"{request.method} {request.path_info}",
            context=span_context,
            attributes=span_attributes,
            kind=trace.SpanKind.SERVER,
        ) as span:
            response = self._middleware_chain(request)
            response._resource_closers.append(request.close)
            self._finish_span(span, response)
            return response

    def _get_response(self, request: Request) -> ResponseBase:
        """
        Resolve and call the view, then apply view, exception, and
        template_response middleware. This method is everything that happens
        inside the request/response middleware.

        When called from aget_response (via executor), async views are
        bridged back to the event loop via run_coroutine_threadsafe.
        """
        import asyncio

        resolver_match = self.resolve_request(request)
        view_func = resolver_match.view

        event_loop = getattr(request, "_event_loop", None)
        if event_loop is not None and inspect.iscoroutinefunction(view_func):
            coro = view_func(request, *resolver_match.args, **resolver_match.kwargs)
            future = asyncio.run_coroutine_threadsafe(coro, event_loop)
            response = future.result()
        else:
            response = view_func(request, *resolver_match.args, **resolver_match.kwargs)

        # Complain if the view returned None (a common error).
        self.check_response(response, view_func)

        return response

    async def aget_response(
        self, request: Request, executor: Any = None
    ) -> ResponseBase:
        """Return a Response for the given Request, supporting async views.

        Runs the full sync middleware chain in an executor thread.
        When the innermost handler encounters an async view, it bridges
        back to the event loop via run_coroutine_threadsafe.
        """
        import asyncio

        assert self._middleware_chain is not None, (
            "load_middleware() must be called before aget_response()"
        )

        loop = asyncio.get_running_loop()
        # Store loop on request so _get_response can bridge async views
        request._event_loop = loop  # type: ignore[attr-defined]

        span_attributes, span_context = self._build_request_span(request)

        with tracer.start_as_current_span(
            f"{request.method} {request.path_info}",
            context=span_context,
            attributes=span_attributes,
            kind=trace.SpanKind.SERVER,
        ) as span:
            response = await loop.run_in_executor(
                executor, self._middleware_chain, request
            )
            response._resource_closers.append(request.close)
            self._finish_span(span, response)
            return response

    def resolve_request(self, request: Request) -> ResolverMatch:
        """
        Retrieve/set the urlrouter for the request. Return the view resolved,
        with its args and kwargs.
        """

        # Reuse resolver_match if already set (avoids double resolution
        # when the worker pre-resolved to check for async views).
        if hasattr(request, "resolver_match") and request.resolver_match is not None:
            resolver_match = request.resolver_match
        else:
            resolver = get_resolver()
            resolver_match = resolver.resolve(request.path_info)

        span = trace.get_current_span()

        # Route makes a better name
        if resolver_match.route:
            # Add leading slash for consistency with HTTP paths
            route_with_slash = f"/{resolver_match.route}"
            span.set_attribute(http_attributes.HTTP_ROUTE, route_with_slash)
            span.update_name(f"{request.method} {route_with_slash}")

        request.resolver_match = resolver_match
        return resolver_match

    def check_response(
        self,
        response: Response | None,
        callback: Callable[..., Response],
        name: str | None = None,
    ) -> None:
        """
        Raise an error if the view returned None or an uncalled coroutine.
        """
        if not name:
            if isinstance(callback, types.FunctionType):  # FBV
                name = f"The view {callback.__module__}.{callback.__name__}"
            else:  # CBV
                name = f"The view {callback.__module__}.{callback.__class__.__name__}.__call__"
        if response is None:
            raise ValueError(
                f"{name} didn't return a Response object. It returned None instead."
            )
