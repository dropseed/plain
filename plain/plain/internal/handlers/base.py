from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
import dataclasses
import inspect
import time
from typing import TYPE_CHECKING, Any

from opentelemetry import context, metrics, trace
from opentelemetry.semconv._incubating.attributes.http_attributes import (
    HTTP_RESPONSE_BODY_SIZE,
)
from opentelemetry.semconv.attributes import (
    client_attributes,
    error_attributes,
    http_attributes,
    network_attributes,
    server_attributes,
    url_attributes,
    user_agent_attributes,
)
from opentelemetry.semconv.metrics.http_metrics import HTTP_SERVER_REQUEST_DURATION

from plain.http import Response
from plain.runtime import settings
from plain.urls import get_resolver
from plain.utils.module_loading import import_string
from plain.utils.otel import format_exception_type

from .exception import response_for_exception

if TYPE_CHECKING:
    from plain.http import Request, ResponseBase
    from plain.http.middleware import HttpMiddleware
    from plain.urls import ResolverMatch


# Builtin middleware that runs before user middleware.
# before_request runs top-down, after_response runs bottom-up (outermost).
BUILTIN_BEFORE_MIDDLEWARE = [
    "plain.internal.middleware.headers.DefaultHeadersMiddleware",
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


# RFC 9110 standard methods + PATCH (RFC 5789).
# Unknown methods get normalized to _OTHER per OTel HTTP semconv.
_KNOWN_HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"}
)

# Context keys for passing request data to the observer sampler.
# Uses context.set_value (process-local) — NOT baggage, which propagates
# across process boundaries and would leak cookies/auth-tokens downstream.
# Uses plain strings (like plain-postgres's _SUPPRESS_KEY) so the observer
# can look them up by the same string without needing to import these.
_REQUEST_COOKIES_KEY = "plain.request.cookies"
_REQUEST_HEADERS_KEY = "plain.request.headers"

tracer = trace.get_tracer("plain")

meter = metrics.get_meter("plain")
request_duration_histogram = meter.create_histogram(
    name=HTTP_SERVER_REQUEST_DURATION,
    unit="s",
    description="Duration of HTTP server requests.",
)


@dataclasses.dataclass
class _AsyncViewPending:
    """Returned by _run_sync_pipeline when an async view needs to be awaited."""

    coroutine: Any
    view_class: type
    ran_before: list[HttpMiddleware]


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

    def _start_request_span(
        self, request: Request
    ) -> contextlib.AbstractContextManager[trace.Span]:
        """Start an OpenTelemetry span for a request and set it as current."""
        method = request.method or ""
        if method not in _KNOWN_HTTP_METHODS:
            span_method = "_OTHER"
        else:
            span_method = method

        span_attributes: dict[str, Any] = {
            "plain.request.id": request.unique_id,
            http_attributes.HTTP_REQUEST_METHOD: span_method,
            url_attributes.URL_PATH: request.path_info,
            url_attributes.URL_SCHEME: request.scheme,
        }

        if span_method == "_OTHER" and method:
            span_attributes[http_attributes.HTTP_REQUEST_METHOD_ORIGINAL] = method

        if request.query_string:
            span_attributes[url_attributes.URL_QUERY] = request.query_string

        if request.server_name:
            span_attributes[server_attributes.SERVER_ADDRESS] = request.server_name
        if request.server_port:
            try:
                span_attributes[server_attributes.SERVER_PORT] = int(
                    request.server_port
                )
            except (TypeError, ValueError):
                pass

        if client_ip := request.client_ip:
            span_attributes[client_attributes.CLIENT_ADDRESS] = client_ip

        if user_agent := request.headers.get("User-Agent"):
            span_attributes[user_agent_attributes.USER_AGENT_ORIGINAL] = user_agent

        # Pass request data to observer sampler via process-local context
        # (not baggage, which would propagate to downstream services).
        span_context = context.set_value(_REQUEST_COOKIES_KEY, request.cookies)
        span_context = context.set_value(
            _REQUEST_HEADERS_KEY, request.headers, span_context
        )

        # Start with just the method; updated to "{method} {route}" after
        # URL resolution in _resolve_request. Avoids high-cardinality span
        # names from raw paths when resolution fails (404, middleware errors).
        span_name = "HTTP" if span_method == "_OTHER" else span_method

        return tracer.start_as_current_span(
            span_name,
            context=span_context,
            attributes=span_attributes,
            kind=trace.SpanKind.SERVER,
        )

    def _finalize_span(self, span: trace.Span, response: ResponseBase) -> None:
        """Set span status and record exceptions from the response."""
        span.set_attribute(
            http_attributes.HTTP_RESPONSE_STATUS_CODE, response.status_code
        )
        if isinstance(response, Response):
            span.set_attribute(HTTP_RESPONSE_BODY_SIZE, len(response.content))
        if response.status_code >= 500:
            span.set_status(trace.StatusCode.ERROR)
            if response.exception:
                span.record_exception(response.exception)
                span.set_attribute(
                    error_attributes.ERROR_TYPE,
                    format_exception_type(response.exception),
                )
            else:
                span.set_attribute(
                    error_attributes.ERROR_TYPE, str(response.status_code)
                )

    async def _run_in_executor(
        self,
        executor: concurrent.futures.Executor,
        ctx: contextvars.Context,
        fn: Any,
        *args: Any,
    ) -> Any:
        """Run `fn` in the executor inside the supplied request context.

        `ctx` is mutated by `ctx.run()` — ContextVar values set inside
        `fn` persist on the same `ctx` object across subsequent
        `_run_in_executor` calls. That keeps per-request state (e.g. the
        DB connection wrapper) request-scoped instead of thread-scoped, so
        async pipelines see consistent state even when their two executor
        calls land on different worker threads.

        The OTel context is layered on top of `contextvars` too, so
        copying `ctx` after the request span is active carries the span
        through executor hops and async tasks without a separate attach.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, ctx.run, fn, *args)

    async def handle(
        self,
        request: Request,
        executor: concurrent.futures.Executor,
    ) -> ResponseBase:
        """Single entry point for handling a request.

        Creates OTel span and runs the full pipeline: before middleware →
        resolve/dispatch view → after middleware.

        A fresh, empty `contextvars.Context` is built per request and
        shared by every phase of the pipeline — both executor hops run
        via `ctx.run()`, and async view coroutines are driven on a task
        bound to the same context via `asyncio.create_task(coro,
        context=request_ctx)`. That keeps middleware state (e.g.
        `DatabaseConnectionMiddleware`'s connection wrapper) request-
        scoped, so `after_response` sees ContextVars that `before_request`
        or the view set regardless of which worker thread it lands on.

        Starting from an empty `Context()` rather than `copy_context()`
        is deliberate: the server task's ambient ContextVar state may
        carry stale values from a previous keep-alive request's
        streaming body, and inheriting that would contaminate this
        request's view of per-request state. The OTel server span is
        attached explicitly below so executor hops and the async task
        still see it.
        """
        assert self._middleware_chain is not None, (
            "load_middleware() must be called before handle()"
        )

        with self._start_request_span(request) as span:
            request_ctx = contextvars.Context()
            # Prime the empty context with the current OTel context
            # (which has the server span active) so `ctx.run` and the
            # async view's task see the span without inheriting
            # anything else from the server task.
            request_ctx.run(context.attach, context.get_current())
            start = time.perf_counter()

            result = await self._run_in_executor(
                executor, request_ctx, self._run_sync_pipeline, request
            )

            if isinstance(result, _AsyncViewPending):
                # Drive the coroutine on a task bound to request_ctx so
                # any ContextVars the view sets (e.g. a DB wrapper via
                # `get_connection()`) land on request_ctx and are visible
                # to after_response below.
                try:
                    task = asyncio.get_running_loop().create_task(
                        result.coroutine, context=request_ctx
                    )
                    response = await task
                    self._check_response(response, result.view_class)
                except Exception as exc:
                    response = response_for_exception(request, exc)

                response = await self._run_in_executor(
                    executor,
                    request_ctx,
                    self._finish_pipeline,
                    request,
                    response,
                    result.ran_before,
                )
            else:
                response = result

            response._resource_closers.append(request.close)
            self._finalize_span(span, response)

            duration_s = time.perf_counter() - start
            method = request.method or ""
            if method not in _KNOWN_HTTP_METHODS:
                method = "_OTHER"
            duration_attrs: dict[str, str | int] = {
                http_attributes.HTTP_REQUEST_METHOD: method,
                http_attributes.HTTP_RESPONSE_STATUS_CODE: response.status_code,
                url_attributes.URL_SCHEME: request.scheme,
                network_attributes.NETWORK_PROTOCOL_NAME: "http",
            }
            if request.resolver_match and request.resolver_match.route:
                duration_attrs[http_attributes.HTTP_ROUTE] = (
                    f"/{request.resolver_match.route}"
                )
            if response.status_code >= 500:
                duration_attrs[error_attributes.ERROR_TYPE] = str(response.status_code)
            request_duration_histogram.record(duration_s, duration_attrs)

            return response

    def _run_sync_pipeline(self, request: Request) -> ResponseBase | _AsyncViewPending:
        """Run the entire sync request pipeline on a single thread.

        Runs before-middleware, resolves and dispatches the view, then runs
        after-middleware.

        If the view is async, returns an _AsyncViewPending so the caller
        can await the coroutine on the event loop.
        """
        # 1. Before middleware
        response, ran_before = self._run_before_request(request)

        # 2. Resolve and dispatch the view
        if response is None:
            try:
                resolver_match = self._resolve_request(request)
                view = resolver_match.view_class(
                    request=request,
                    url_kwargs=resolver_match.kwargs,
                )
                response = view.get_response()
                view_class = type(view)

                # Async views return a coroutine that must be awaited
                if inspect.iscoroutine(response):
                    return _AsyncViewPending(
                        coroutine=response,
                        view_class=view_class,
                        ran_before=ran_before,
                    )

                self._check_response(response, view_class)
            except Exception as exc:
                response = response_for_exception(request, exc)

        # 3. After middleware
        return self._finish_pipeline(request, response, ran_before)

    def _finish_pipeline(
        self,
        request: Request,
        response: ResponseBase,
        ran_before: list[HttpMiddleware],
    ) -> ResponseBase:
        """Run after-middleware.

        Always runs inside the request's shared `ctx.run(request_ctx)`,
        so it sees any ContextVars that `before_request` or the view set.
        For async views it may land on a different executor thread than
        before-middleware; the shared context bridges that gap.
        """
        return self._run_after_response(request, response, ran_before)

    def _resolve_request(self, request: Request) -> ResolverMatch:
        """Resolve the URL, caching on request.resolver_match."""
        if request.resolver_match is not None:
            resolver_match = request.resolver_match
        else:
            resolver = get_resolver()
            resolver_match = resolver.resolve(request.path_info)
            request.resolver_match = resolver_match

        # Update span with route info
        span = trace.get_current_span()
        if resolver_match.route:
            route_with_slash = f"/{resolver_match.route}"
            span.set_attribute(http_attributes.HTTP_ROUTE, route_with_slash)
            method = request.method or ""
            span_method = method if method in _KNOWN_HTTP_METHODS else "HTTP"
            span.update_name(f"{span_method} {route_with_slash}")

        return resolver_match

    def _run_before_request(
        self, request: Request
    ) -> tuple[ResponseBase | None, list[HttpMiddleware]]:
        """Run before_request forward through middleware chain."""
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

    def _run_after_response(
        self,
        request: Request,
        response: ResponseBase,
        ran_before: list[HttpMiddleware],
    ) -> ResponseBase:
        """Run after_response in reverse through middleware that ran before_request."""
        for mw in reversed(ran_before):
            try:
                response = mw.after_response(request, response)  # ty: ignore[invalid-argument-type]
            except Exception as exc:
                response = response_for_exception(request, exc)

        return response

    def _check_response(
        self,
        response: ResponseBase | None,
        view_class: type,
    ) -> None:
        """Raise an error if the view returned None."""
        if response is None:
            name = f"{view_class.__module__}.{view_class.__qualname__}"
            raise ValueError(
                f"The view {name} didn't return a Response object. It returned None instead."
            )
