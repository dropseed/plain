import asyncio
import hashlib
import os
from io import BytesIO

from opentelemetry import trace
from opentelemetry.semconv.attributes.code_attributes import (
    CODE_FILE_PATH,
    CODE_FUNCTION_NAME,
    CODE_LINE_NUMBER,
)
from opentelemetry.semconv.attributes.db_attributes import (
    DB_OPERATION_NAME,
    DB_QUERY_TEXT,
)
from plain.http import (
    ForbiddenError403,
    JsonResponse,
    Response,
    StreamingResponse,
    WebSocket,
)
from plain.urls import Router, path
from plain.views import View

_tracer = trace.get_tracer("plain.tests")

# One path under the working directory (shortens to a relative app path) and
# one under `site-packages` (shortens to its package path) — the two display
# shortenings `plain request` applies to call sites.
_APP_FILE = os.path.join(os.getcwd(), "app", "views.py")
_DEPENDENCY_FILE = os.path.join(
    os.getcwd(), ".venv", "lib", "site-packages", "plain", "sessions", "core.py"
)


class TestView(View):
    def get(self):
        return Response("Hello, world!")


class StreamView(View):
    """Returns a streaming response, which has no readable `.content`."""

    def get(self):
        return StreamingResponse(BytesIO(b"streamed-bytes"), content_type="text/plain")


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


def _query_span(sql: str, *, file_path: str, function: str, line: int) -> None:
    """Emit a span shaped like the one a db instrumentation would record."""
    with _tracer.start_as_current_span(
        sql.split()[0],
        kind=trace.SpanKind.CLIENT,
        attributes={
            DB_QUERY_TEXT: sql,
            DB_OPERATION_NAME: sql.split()[0],
            CODE_FILE_PATH: file_path,
            CODE_FUNCTION_NAME: function,
            CODE_LINE_NUMBER: line,
        },
    ):
        pass


class QueriesView(View):
    """Emits the span shape a request with an N+1 produces.

    The repeated statement is issued once by a dependency and three times by
    app code, exercising call-site dedup and path shortening for both kinds
    of sites.
    """

    def get(self):
        _query_span(
            'SELECT "u"."id", "u"."email" FROM "u" WHERE "u"."id" = %s',
            file_path=_DEPENDENCY_FILE,
            function="_get_session_data",
            line=92,
        )
        for _ in range(3):
            _query_span(
                'SELECT "u"."id", "u"."email" FROM "u" WHERE "u"."id" = %s',
                file_path=_APP_FILE,
                function="index",
                line=41,
            )
        _query_span(
            'SELECT "slow"."id" FROM "slow"',
            file_path=_APP_FILE,
            function="index",
            line=52,
        )
        _query_span(
            'SAVEPOINT "s1"',
            file_path=_DEPENDENCY_FILE,
            function="save",
            line=172,
        )
        return Response("queried")


class BoomView(View):
    """Raises, so the CLI's failure path can be exercised."""

    def get(self):
        raise ValueError("kaboom")


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
        path("upload", UploadView, name="upload"),
        path("echo-body", EchoBodyView, name="echo_body"),
        path("multipart-echo", MultipartEchoView, name="multipart_echo"),
        path("queries", QueriesView, name="queries"),
        path("boom", BoomView, name="boom"),
    )
