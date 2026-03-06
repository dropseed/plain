from __future__ import annotations

import types
from typing import TYPE_CHECKING

from opentelemetry import baggage, trace
from opentelemetry.semconv.attributes import http_attributes, url_attributes

from plain.runtime import settings
from plain.urls import get_resolver
from plain.utils.module_loading import import_string

from .exception import response_for_exception

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.http import Request, Response, ResponseBase
    from plain.http.middleware import HttpMiddleware
    from plain.urls import ResolverMatch


# Builtin middleware that runs before user middleware.
# before_request runs top-down, after_response runs bottom-up (outermost).
BUILTIN_BEFORE_MIDDLEWARE = [
    "plain.internal.middleware.headers.DefaultHeadersMiddleware",
    "plain.internal.middleware.healthcheck.HealthcheckMiddleware",
    "plain.internal.middleware.hosts.HostValidationMiddleware",
    "plain.internal.middleware.https.HttpsRedirectMiddleware",
    "plain.csrf.middleware.CsrfViewMiddleware",
]

# Builtin middleware that runs after user middleware (closest to the view).
# after_response runs first, so replacements (e.g. slash redirect) happen
# before user middleware modifies the response (e.g. session cookies).
BUILTIN_AFTER_MIDDLEWARE = [
    "plain.internal.middleware.slash.RedirectSlashMiddleware",
]


tracer = trace.get_tracer("plain")


class BaseHandler:
    _middleware_chain: list[HttpMiddleware] | None = None

    def load_middleware(self) -> None:
        """
        Populate middleware list from settings.MIDDLEWARE.

        Must be called after the environment is fixed (see __call__ in subclasses).
        """
        middleware_paths = (
            BUILTIN_BEFORE_MIDDLEWARE + settings.MIDDLEWARE + BUILTIN_AFTER_MIDDLEWARE
        )

        chain: list[HttpMiddleware] = []
        for middleware_path in middleware_paths:
            middleware_class = import_string(middleware_path)
            mw_instance = middleware_class()
            chain.append(mw_instance)

        # We only assign to this when initialization is complete as it is used
        # as a flag for initialization being complete.
        self._middleware_chain = chain

    def get_response(self, request: Request) -> ResponseBase:
        """Return a Response object for the given Request."""
        assert self._middleware_chain is not None, (
            "load_middleware() must be called before get_response()"
        )

        span_attributes: dict[str, str] = {
            "plain.request.id": request.unique_id,
            http_attributes.HTTP_REQUEST_METHOD: request.method or "",
            url_attributes.URL_PATH: request.path_info,
            url_attributes.URL_SCHEME: request.scheme,
        }

        # Add full URL if we can build it
        try:
            span_attributes[url_attributes.URL_FULL] = request.build_absolute_uri()
        except (KeyError, AttributeError):
            pass

        # Add query string if present
        if request.query_string:
            span_attributes[url_attributes.URL_QUERY] = request.query_string

        span_context = baggage.set_baggage("http.request.cookies", request.cookies)
        span_context = baggage.set_baggage(
            "http.request.headers", request.headers, span_context
        )

        with tracer.start_as_current_span(
            f"{request.method} {request.path_info}",
            context=span_context,
            attributes=span_attributes,
            kind=trace.SpanKind.SERVER,
        ) as span:
            response = self._run_middleware(request)
            response._resource_closers.append(request.close)

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

            return response

    def _run_middleware(self, request: Request) -> ResponseBase:
        """
        Run the two-phase middleware pipeline:
        1. before_request — forward through list, stop on first Response
        2. View call (if no short-circuit)
        3. after_response — reverse through middleware that ran before_request
        """
        chain = self._middleware_chain
        assert chain is not None

        response = None
        # Track which middleware completed before_request (for unwinding)
        ran_before: list[HttpMiddleware] = []

        # Phase 1: before_request (forward)
        for mw in chain:
            try:
                result = mw.before_request(request)
            except Exception as exc:
                response = response_for_exception(request, exc)
                # This middleware's before_request raised, so it doesn't get
                # after_response. Unwind only previously completed middleware.
                break

            ran_before.append(mw)

            if result is not None:
                # Short-circuit: this middleware returned a response
                response = result
                break

        # Phase 2: View call (if no short-circuit)
        if response is None:
            try:
                response = self._get_response(request)
            except Exception as exc:
                response = response_for_exception(request, exc)

        # Phase 3: after_response (reverse through middleware that ran before_request)
        for mw in reversed(ran_before):
            try:
                response = mw.after_response(request, response)  # type: ignore[arg-type]
            except Exception as exc:
                response = response_for_exception(request, exc)

        return response

    def _get_response(self, request: Request) -> ResponseBase:
        """
        Resolve and call the view. This method is everything that happens
        inside the request/response middleware.
        """
        resolver_match = self.resolve_request(request)

        response = resolver_match.view(
            request, *resolver_match.args, **resolver_match.kwargs
        )

        # Complain if the view returned None (a common error).
        self.check_response(response, resolver_match.view)

        return response

    def resolve_request(self, request: Request) -> ResolverMatch:
        """
        Retrieve/set the urlrouter for the request. Return the view resolved,
        with its args and kwargs.
        """

        resolver = get_resolver()
        # Resolve the view, and assign the match object back to the request.
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
