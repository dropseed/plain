"""Test middleware and view classes for test_middleware_pipeline.py."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

from opentelemetry import trace

from plain.http import HttpMiddleware, Response
from plain.urls import Router, path
from plain.views import ServerSentEvent, ServerSentEventsView, View

# Shared log that tests can inspect and clear
call_log: list[str] = []

# Exercised by the cross-thread context-propagation test — `before_request`
# stashes a value here and `after_response` reads it back.
request_ctxvar: ContextVar[str | None] = ContextVar("request_ctxvar", default=None)
ctxvar_seen: list[str | None] = []


class CtxVarRoundTripMiddleware(HttpMiddleware):
    """Writes a sentinel in `before_request`, reads it back in `after_response`."""

    def before_request(self, request):
        request_ctxvar.set("set-by-before-request")
        return None

    def after_response(self, request, response):
        ctxvar_seen.append(request_ctxvar.get())
        return response


class AsyncAwaitView(View):
    """Async view that yields to the event loop so the executor hop splits."""

    async def get(self) -> Response:  # ty: ignore[invalid-method-override]
        await asyncio.sleep(0)
        return Response("ok")


class AsyncCtxVarRouter(Router):
    namespace = ""
    urls = [
        path("", AsyncAwaitView, name="index"),
    ]


class SyncSpanEmittingView(View):
    """Sync view that emits a child span across the executor hop."""

    def get(self) -> Response:
        tracer = trace.get_tracer("plain.tests")
        with tracer.start_as_current_span("view-child-span"):
            return Response("ok")


class SyncSpanRouter(Router):
    namespace = ""
    urls = [
        path("", SyncSpanEmittingView, name="index"),
    ]


class AsyncSpanEmittingView(View):
    """Async view that emits a child span across the asyncio task hop."""

    async def get(self) -> Response:  # ty: ignore[invalid-method-override]
        tracer = trace.get_tracer("plain.tests")
        with tracer.start_as_current_span("view-child-span"):
            await asyncio.sleep(0)
        return Response("ok")


class AsyncSpanRouter(Router):
    namespace = ""
    urls = [
        path("", AsyncSpanEmittingView, name="index"),
    ]


class TrackingMiddleware(HttpMiddleware):
    def before_request(self, request):
        call_log.append("before")
        return None

    def after_response(self, request, response):
        call_log.append("after")
        return response


class FirstMiddleware(HttpMiddleware):
    def before_request(self, request):
        call_log.append("first_before")
        return None

    def after_response(self, request, response):
        call_log.append("first_after")
        return response


class SecondMiddleware(HttpMiddleware):
    def before_request(self, request):
        call_log.append("second_before")
        return None

    def after_response(self, request, response):
        call_log.append("second_after")
        return response


class BlockingMiddleware(HttpMiddleware):
    def before_request(self, request):
        call_log.append("blocking")
        return Response("blocked", status_code=403)


class InnerMiddleware(HttpMiddleware):
    def before_request(self, request):
        call_log.append("inner")
        return None


class LoggingMiddleware(HttpMiddleware):
    def before_request(self, request):
        call_log.append("user_middleware")
        return None


class ExplodingMiddleware(HttpMiddleware):
    def before_request(self, request):
        raise RuntimeError("middleware boom")


class OuterWrappingMiddleware(HttpMiddleware):
    """Outer middleware that logs before/after and records the response status."""

    def before_request(self, request):
        call_log.append("outer_before")
        return None

    def after_response(self, request, response):
        call_log.append(f"outer_after:{response.status_code}")
        return response


class InnerExplodingMiddleware(HttpMiddleware):
    """Inner middleware that raises after logging."""

    def before_request(self, request):
        call_log.append("inner_explode_before")
        raise RuntimeError("inner boom")


class ResponseModifyingMiddleware(HttpMiddleware):
    """Middleware that adds a header after getting the response."""

    def after_response(self, request, response):
        response.headers["X-Modified-By"] = "ResponseModifyingMiddleware"
        return response


class SetupTeardownMiddleware(HttpMiddleware):
    """Middleware with both setup and teardown that can short-circuit."""

    def before_request(self, request):
        call_log.append("setup")
        if request.headers.get("X-Block"):
            return Response("nope", status_code=403)
        return None

    def after_response(self, request, response):
        call_log.append("teardown")
        return response


class ErrorView(View):
    def get(self):
        raise RuntimeError("boom")


class ErrorRouter(Router):
    namespace = ""
    urls = [
        path("", ErrorView, name="index"),
    ]


class FiniteServerSentEventsView(ServerSentEventsView):
    """ServerSentEventsView that yields a few events and stops (for testing)."""

    async def stream(self):
        yield ServerSentEvent(data="hello")
        yield ServerSentEvent(data={"count": 1})
        yield ServerSentEvent(data="done", event="finish", id="msg-3")


class SSERouter(Router):
    namespace = ""
    urls = [
        path("", FiniteServerSentEventsView, name="index"),
    ]
