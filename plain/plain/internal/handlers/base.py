from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import inspect
from typing import TYPE_CHECKING, Any

from opentelemetry import baggage, context, trace
from opentelemetry.semconv.attributes import http_attributes, url_attributes

from plain import signals
from plain.runtime import settings
from plain.urls import get_resolver
from plain.utils.module_loading import import_string

from .exception import response_for_exception

if TYPE_CHECKING:
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

    async def _run_in_executor(
        self,
        executor: concurrent.futures.Executor,
        fn: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a sync function in the executor, propagating OTel context."""
        loop = asyncio.get_running_loop()
        ctx = context.get_current()

        def _wrapper() -> Any:
            token = context.attach(ctx)
            try:
                return fn(*args, **kwargs)
            finally:
                context.detach(token)

        return await loop.run_in_executor(executor, _wrapper)

    async def handle(
        self,
        request: Request,
        executor: concurrent.futures.Executor,
    ) -> ResponseBase:
        """Single entry point for handling a request.

        Creates OTel span and runs the full pipeline: signal → before
        middleware → resolve/dispatch view → after middleware → signal.

        For sync views, the entire pipeline runs in a single executor call
        so that signals, middleware, and the view all execute on the same
        thread (preserving thread-local DB connection assumptions).

        For async views, the sync portion (signal + before middleware +
        URL resolution) runs in one executor call, the coroutine is awaited
        on the event loop, then after-middleware + request_finished runs in
        a second executor call.
        """
        assert self._middleware_chain is not None, (
            "load_middleware() must be called before handle()"
        )

        span_attributes, span_context = self._build_request_span(request)

        with tracer.start_as_current_span(
            f"{request.method} {request.path_info}",
            context=span_context,
            attributes=span_attributes,
            kind=trace.SpanKind.SERVER,
        ) as span:
            result = await self._run_in_executor(
                executor, self._run_sync_pipeline, request
            )

            if isinstance(result, _AsyncViewPending):
                # Async view: await the coroutine on the event loop, then
                # run after-middleware + request_finished back in the executor.
                try:
                    response = await result.coroutine
                    self._check_response(response, result.view_class)
                except Exception as exc:
                    response = response_for_exception(request, exc)

                response = await self._run_in_executor(
                    executor,
                    self._finish_pipeline,
                    request,
                    response,
                    result.ran_before,
                )
            else:
                response = result

            response._resource_closers.append(request.close)
            self._finalize_span(span, response)
            return response

    def _run_sync_pipeline(self, request: Request) -> ResponseBase | _AsyncViewPending:
        """Run the entire sync request pipeline on a single thread.

        Sends request_started, runs before-middleware, resolves and dispatches
        the view, runs after-middleware, and sends request_finished.

        If the view is async, returns an _AsyncViewPending so the caller
        can await the coroutine on the event loop.
        """
        signals.request_started.send(sender=self.__class__, request=request)

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

        # 3. After middleware + request_finished signal
        return self._finish_pipeline(request, response, ran_before)

    def _finish_pipeline(
        self,
        request: Request,
        response: ResponseBase,
        ran_before: list[HttpMiddleware],
    ) -> ResponseBase:
        """Run after-middleware and send request_finished signal.

        For sync views, this runs on the same thread as request_started
        (part of the single _run_sync_pipeline call).

        For async views, this runs in a separate executor call and may
        land on a different thread than request_started. Thread-local
        state from request_started is not guaranteed to be available.
        In practice this is safe because close_old_connections (the main
        signal handler) is idempotent per-thread.

        The signal fires before streaming response bodies are transmitted.
        Handlers like close_old_connections should not affect in-progress
        streams since request_started on the next request also handles
        stale connections.
        """
        response = self._run_after_response(request, response, ran_before)
        signals.request_finished.send(sender=self.__class__)
        return response

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
            span.update_name(f"{request.method} {route_with_slash}")

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
                response = mw.after_response(request, response)  # type: ignore[arg-type]
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
