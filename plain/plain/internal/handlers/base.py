from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import types
from typing import TYPE_CHECKING

from opentelemetry import baggage, context, trace
from opentelemetry.semconv.attributes import http_attributes, url_attributes

from plain.runtime import settings
from plain.urls import get_resolver
from plain.utils.module_loading import import_string

from .exception import response_for_exception

if TYPE_CHECKING:
    from collections.abc import Callable

    from plain.http import Request, ResponseBase
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

    def _build_request_span(
        self, request: Request
    ) -> tuple[dict[str, str], context.Context]:
        """Build OpenTelemetry span attributes and baggage context for a request."""
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

    def _finalize_span(self, span: trace.Span, response: ResponseBase) -> None:
        """Set span status and record exceptions from the response."""
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
            response = self._run_middleware(request)
            response._resource_closers.append(request.close)
            self._finalize_span(span, response)
            return response

    def is_async_view(self, request: Request) -> bool:
        """Check whether the resolved view callable is async.

        Returns False if resolution fails (e.g. 404) — the caller
        should fall back to sync dispatch, where the 404 will be
        raised and handled normally.
        """
        try:
            resolver = get_resolver()
            resolver_match = resolver.resolve(request.path_info)
            return inspect.iscoroutinefunction(resolver_match.view)
        except Exception:
            return False

    async def get_response_async(
        self, request: Request, executor: concurrent.futures.Executor | None = None
    ) -> ResponseBase:
        """Async version of get_response for views with async handlers.

        Runs middleware sync phases in the given executor (thread pool),
        and awaits async view handlers on the event loop.
        """
        assert self._middleware_chain is not None, (
            "load_middleware() must be called before get_response_async()"
        )

        span_attributes, span_context = self._build_request_span(request)

        with tracer.start_as_current_span(
            f"{request.method} {request.path_info}",
            context=span_context,
            attributes=span_attributes,
            kind=trace.SpanKind.SERVER,
        ) as span:
            response = await self._run_middleware_async(request, executor)
            response._resource_closers.append(request.close)
            self._finalize_span(span, response)
            return response

    def _run_middleware(self, request: Request) -> ResponseBase:
        """
        Run the two-phase middleware pipeline:
        1. before_request — forward through list, stop on first Response
        2. View call (if no short-circuit)
        3. after_response — reverse through middleware that ran before_request
        """
        response, ran_before = self.run_before_request(request)

        # Phase 2: View call (if no short-circuit)
        if response is None:
            try:
                response = self._get_response(request)
            except Exception as exc:
                response = response_for_exception(request, exc)

        # Phase 3: after_response
        response = self.run_after_response(request, response, ran_before)

        return response

    async def _run_middleware_async(
        self, request: Request, executor: concurrent.futures.Executor | None = None
    ) -> ResponseBase:
        """Async middleware pipeline: sync phases in executor, async view on event loop."""
        loop = asyncio.get_running_loop()
        # Capture OTel context so executor threads see the active span
        ctx = context.get_current()

        def _run_before() -> tuple[ResponseBase | None, list[HttpMiddleware]]:
            token = context.attach(ctx)
            try:
                return self.run_before_request(request)
            finally:
                context.detach(token)

        # Phase 1: before_request in executor
        response, ran_before = await loop.run_in_executor(executor, _run_before)

        # Phase 2: View call (async on event loop, sync in executor)
        if response is None:
            try:
                response = await self._get_response_async(request, executor)
            except Exception as exc:
                response = response_for_exception(request, exc)

        def _run_after() -> ResponseBase:
            token = context.attach(ctx)
            try:
                return self.run_after_response(request, response, ran_before)
            finally:
                context.detach(token)

        # Phase 3: after_response in executor
        response = await loop.run_in_executor(executor, _run_after)

        return response

    def run_before_request(
        self, request: Request
    ) -> tuple[ResponseBase | None, list[HttpMiddleware]]:
        """
        Phase 1: Run before_request forward through middleware chain.
        Returns (response_or_none, list_of_middleware_that_completed).
        """
        chain = self._middleware_chain
        assert chain is not None

        response = None
        ran_before: list[HttpMiddleware] = []

        for mw in chain:
            try:
                result = mw.before_request(request)
            except Exception as exc:
                response = response_for_exception(request, exc)
                break

            ran_before.append(mw)

            if result is not None:
                response = result
                break

        return response, ran_before

    def run_after_response(
        self,
        request: Request,
        response: ResponseBase,
        ran_before: list[HttpMiddleware],
    ) -> ResponseBase:
        """
        Phase 3: Run after_response in reverse through middleware that ran before_request.
        """
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

        Only handles sync views. Async views (e.g. ServerSentEventsView)
        go through _get_response_async via the async dispatch path.
        """
        resolver_match = self.resolve_request(request)

        view = resolver_match.view
        response = view(request, *resolver_match.args, **resolver_match.kwargs)

        # Complain if the view returned None (a common error).
        self.check_response(response, view)

        return response

    async def _get_response_async(
        self, request: Request, executor: concurrent.futures.Executor | None = None
    ) -> ResponseBase:
        """Resolve and call the view, dispatching async views on the event loop."""
        loop = asyncio.get_running_loop()
        resolver_match = self.resolve_request(request)

        view = resolver_match.view
        if inspect.iscoroutinefunction(view):
            response = await view(
                request, *resolver_match.args, **resolver_match.kwargs
            )
        else:
            # Propagate OTel context so the sync view sees the active span
            ctx = context.get_current()

            def _call_view() -> ResponseBase:
                token = context.attach(ctx)
                try:
                    return view(request, *resolver_match.args, **resolver_match.kwargs)
                finally:
                    context.detach(token)

            response = await loop.run_in_executor(executor, _call_view)

        self.check_response(response, view)
        return response

    def resolve_request(self, request: Request) -> ResolverMatch:
        """
        Retrieve/set the urlrouter for the request. Return the view resolved,
        with its args and kwargs.

        Caches the result on request.resolver_match so repeated calls
        (e.g. early detection in the worker + later call inside the span)
        only resolve once. Always updates the current span with route info.
        """
        if request.resolver_match is not None:
            resolver_match = request.resolver_match
        else:
            resolver = get_resolver()
            resolver_match = resolver.resolve(request.path_info)
            request.resolver_match = resolver_match

        # Always update span — may be called from different span contexts
        span = trace.get_current_span()
        if resolver_match.route:
            route_with_slash = f"/{resolver_match.route}"
            span.set_attribute(http_attributes.HTTP_ROUTE, route_with_slash)
            span.update_name(f"{request.method} {route_with_slash}")

        return resolver_match

    def check_response(
        self,
        response: ResponseBase | None,
        callback: Callable[..., ResponseBase],
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
