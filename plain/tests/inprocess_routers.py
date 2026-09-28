"""Views for `tests/public/test_inprocess_server.py`."""

import contextvars

from plain.http import AsyncStreamingResponse, Response, StreamingResponse
from plain.urls import Router, path
from plain.views import View

# Set by a test before it makes a request, read by the views below.
caller_value: contextvars.ContextVar[str] = contextvars.ContextVar(
    "caller_value", default="unset"
)


class NoContentWithLengthView(View):
    def get(self):
        response = Response(status_code=204)
        response.headers["Content-Length"] = "0"
        return response


class NotModifiedWithLengthView(View):
    def get(self):
        response = Response(status_code=304)
        response.headers["Content-Length"] = "11"
        return response


class RaisingView(View):
    def get(self):
        raise RuntimeError("in-process view boom")


class CallerValueView(View):
    """Answers with what the caller's context holds when the view runs."""

    def get(self):
        return Response(caller_value.get())


class CallerValueStreamView(View):
    """Answers with what the caller's context holds when the body runs."""

    def get(self):
        def chunks():
            yield caller_value.get().encode()

        return StreamingResponse(chunks(), content_type="text/plain")


class AsyncView(View):
    async def get(self) -> Response:  # ty: ignore[invalid-method-override]
        return Response("from an async view")


class AsyncRaisingView(View):
    async def get(self) -> Response:  # ty: ignore[invalid-method-override]
        raise RuntimeError("async view boom")


class AsyncStreamView(View):
    def get(self):
        async def chunks():
            yield b"one "
            yield b"two"

        return AsyncStreamingResponse(chunks(), content_type="text/plain")


class InProcessRouter(Router):
    namespace = ""
    urls = (
        path("no-content", NoContentWithLengthView, name="no_content"),
        path("not-modified", NotModifiedWithLengthView, name="not_modified"),
        path("raises", RaisingView, name="raises"),
        path("caller-value", CallerValueView, name="caller_value"),
        path("caller-value-stream", CallerValueStreamView, name="caller_value_stream"),
        path("async", AsyncView, name="async"),
        path("async-raises", AsyncRaisingView, name="async_raises"),
        path("async-stream", AsyncStreamView, name="async_stream"),
    )
