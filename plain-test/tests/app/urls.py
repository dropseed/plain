import asyncio
from io import BytesIO

from plain.http import (
    AsyncStreamingResponse,
    FileResponse,
    ForbiddenError403,
    Response,
    StreamingResponse,
    WebSocket,
)
from plain.urls import Router, path
from plain.views import View


class IndexView(View):
    def get(self):
        return Response("Hello, world!")


class StreamView(View):
    """Returns a streaming response, which has no readable `.content`."""

    def get(self):
        return StreamingResponse(BytesIO(b"streamed-bytes"), content_type="text/plain")


class StreamGeneratorView(View):
    """Streams its body from a generator, the way a lazy export would."""

    def get(self):
        def lines():
            yield b"line 1\n"
            yield b"line 2\n"

        return StreamingResponse(lines(), content_type="text/plain")


class FileView(View):
    """Serves a file-backed response."""

    def get(self):
        return FileResponse(BytesIO(b"file bytes"), content_type="text/plain")


class AsyncStreamFailsView(View):
    """Streams one event, then raises — an async body that fails partway."""

    def get(self):
        async def events():
            yield b"data: 1\n\n"
            raise ValueError("feed failed")

        return AsyncStreamingResponse(events(), content_type="text/event-stream")


class StreamFailsFirstView(View):
    """Streams nothing — the body raises before its first chunk."""

    def get(self):
        def lines():
            raise ValueError("query failed")
            yield b"never"

        return StreamingResponse(lines(), content_type="text/plain")


class StreamFailsView(View):
    """Streams one line, then raises — a body that fails after the status."""

    def get(self):
        def lines():
            yield b"line 1\n"
            raise ValueError("export failed")

        return StreamingResponse(lines(), content_type="text/plain")


class EchoBodyView(View):
    """Echoes back the byte count of the raw request body."""

    def post(self):
        return Response(str(len(self.request.body)))


class EchoWebSocketView(View):
    """Serves a page on GET and echoes every message on its socket."""

    websocket_subprotocols = ("echo", "binary")

    def get(self):
        return Response("websocket page")

    async def websocket(self, ws: WebSocket) -> None:
        async for message in ws:
            await ws.send(message)


class RaisingWebSocketView(View):
    async def websocket(self, ws: WebSocket) -> None:
        raise RuntimeError("websocket view boom")


class SleepingWebSocketView(View):
    """Never reads the socket — what a push-only view looks like when idle."""

    async def websocket(self, ws: WebSocket) -> None:
        await asyncio.sleep(3600)


class TalkingWebSocketView(View):
    """Keeps sending after the peer has gone; `send` must raise, not log."""

    async def websocket(self, ws: WebSocket) -> None:
        async for _ in ws:
            pass
        await ws.send("still here?")


class ClosingWebSocketView(View):
    """Closes the socket itself, with an application code."""

    async def websocket(self, ws: WebSocket) -> None:
        await ws.send("bye")
        await ws.close(4000, "done here")


class ForbiddenWebSocketView(EchoWebSocketView):
    def before_request(self) -> None:
        raise ForbiddenError403("not for you")


class AppRouter(Router):
    namespace = ""
    urls = (
        path("", IndexView, name="index"),
        path("websocket/echo", EchoWebSocketView, name="websocket_echo"),
        path("websocket/raises", RaisingWebSocketView, name="websocket_raises"),
        path("websocket/sleeps", SleepingWebSocketView, name="websocket_sleeps"),
        path("websocket/talks", TalkingWebSocketView, name="websocket_talks"),
        path("websocket/closes", ClosingWebSocketView, name="websocket_closes"),
        path("websocket/forbidden", ForbiddenWebSocketView, name="websocket_forbidden"),
        path("stream", StreamView, name="stream"),
        path("stream-generator", StreamGeneratorView, name="stream_generator"),
        path("stream-fails", StreamFailsView, name="stream_fails"),
        path("stream-fails-first", StreamFailsFirstView, name="stream_fails_first"),
        path("file", FileView, name="file"),
        path("async-stream-fails", AsyncStreamFailsView, name="async_stream_fails"),
        path("echo-body", EchoBodyView, name="echo_body"),
    )
