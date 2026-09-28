import asyncio
import hashlib
from io import BytesIO

from plain.http import (
    AsyncStreamingResponse,
    FileResponse,
    ForbiddenError403,
    JsonResponse,
    Response,
    StreamingResponse,
    WebSocket,
)
from plain.urls import Router, path
from plain.views import View


class TestView(View):
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


class UploadView(View):
    """Echoes back the handler class and byte count of an uploaded file."""

    def post(self):
        uploaded = self.request.files["upload"]
        return Response(f"{type(uploaded).__name__}:{len(uploaded.read())}")


class EchoBodyView(View):
    """Echoes back the byte count of the raw request body."""

    def post(self):
        return Response(str(len(self.request.body)))


class MultipartEchoView(View):
    """Describes everything the multipart parser produced for a request.

    File contents come back as a sha256 digest so large uploads can be
    compared byte-for-byte without shipping the bytes through the response.
    """

    def post(self):
        return JsonResponse(
            {
                "form_data": dict(self.request.form_data.lists()),
                "files": [
                    {
                        "field_name": field_name,
                        "name": uploaded.name,
                        "content_type": uploaded.content_type,
                        # The parser hands back `charset` as bytes rather than
                        # str, so repr() is what keeps that visible through JSON.
                        "charset_repr": repr(uploaded.charset),
                        "size": uploaded.size,
                        "handler": type(uploaded).__name__,
                        "sha256": hashlib.sha256(uploaded.read()).hexdigest(),
                    }
                    for field_name, uploads in self.request.files.lists()
                    for uploaded in uploads
                ],
            }
        )


class EchoWebSocketView(View):
    """Serves a page on GET and echoes every message on its socket."""

    websocket_subprotocols = ("echo", "binary")

    def get(self):
        return Response("websocket page")

    async def websocket(self, ws: WebSocket) -> None:
        async for message in ws:
            await ws.send(message)


class SmallLimitWebSocketView(EchoWebSocketView):
    websocket_max_message_size = 16


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
        path("", TestView, name="index"),
        path("websocket/echo", EchoWebSocketView, name="websocket_echo"),
        path("websocket/small", SmallLimitWebSocketView, name="websocket_small"),
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
        path("upload", UploadView, name="upload"),
        path("echo-body", EchoBodyView, name="echo_body"),
        path("multipart-echo", MultipartEchoView, name="multipart_echo"),
    )
