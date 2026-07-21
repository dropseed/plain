from __future__ import annotations

from io import BytesIO

from plain.http import Response, StreamingResponse
from plain.urls import Router, path
from plain.views import View


class TestView(View):
    def get(self):
        return Response("Hello, world!")


class StreamView(View):
    """Returns a streaming response, which has no readable `.content`."""

    def get(self):
        return StreamingResponse(BytesIO(b"streamed-bytes"), content_type="text/plain")


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", TestView, name="index"),
        path("stream", StreamView, name="stream"),
    ]
