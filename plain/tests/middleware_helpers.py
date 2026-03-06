"""Test middleware and view classes for test_middleware_pipeline.py."""

from __future__ import annotations

from plain.http import HttpMiddleware, Response
from plain.urls import Router, path
from plain.views import View

# Shared log that tests can inspect and clear
call_log: list[str] = []


class TrackingMiddleware(HttpMiddleware):
    def process_request(self, request):
        call_log.append("before")
        response = self.get_response(request)
        call_log.append("after")
        return response


class FirstMiddleware(HttpMiddleware):
    def process_request(self, request):
        call_log.append("first_before")
        response = self.get_response(request)
        call_log.append("first_after")
        return response


class SecondMiddleware(HttpMiddleware):
    def process_request(self, request):
        call_log.append("second_before")
        response = self.get_response(request)
        call_log.append("second_after")
        return response


class BlockingMiddleware(HttpMiddleware):
    def process_request(self, request):
        call_log.append("blocking")
        return Response("blocked", status_code=403)


class InnerMiddleware(HttpMiddleware):
    def process_request(self, request):
        call_log.append("inner")
        return self.get_response(request)


class LoggingMiddleware(HttpMiddleware):
    def process_request(self, request):
        call_log.append("user_middleware")
        return self.get_response(request)


class ExplodingMiddleware(HttpMiddleware):
    def process_request(self, request):
        raise RuntimeError("middleware boom")


class OuterWrappingMiddleware(HttpMiddleware):
    """Outer middleware that logs before/after and records the response status."""

    def process_request(self, request):
        call_log.append("outer_before")
        response = self.get_response(request)
        call_log.append(f"outer_after:{response.status_code}")
        return response


class InnerExplodingMiddleware(HttpMiddleware):
    """Inner middleware that raises after logging."""

    def process_request(self, request):
        call_log.append("inner_explode_before")
        raise RuntimeError("inner boom")


class ResponseModifyingMiddleware(HttpMiddleware):
    """Middleware that adds a header after getting the response."""

    def process_request(self, request):
        response = self.get_response(request)
        response.headers["X-Modified-By"] = "ResponseModifyingMiddleware"
        return response


class SetupTeardownMiddleware(HttpMiddleware):
    """Middleware with both setup and teardown that can short-circuit."""

    def process_request(self, request):
        call_log.append("setup")
        if request.headers.get("X-Block"):
            return Response("nope", status_code=403)
        response = self.get_response(request)
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
