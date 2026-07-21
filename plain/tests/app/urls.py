from __future__ import annotations

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

from plain.http import Response, StreamingResponse
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


class AppRouter(Router):
    namespace = ""
    urls = [
        path("", TestView, name="index"),
        path("stream", StreamView, name="stream"),
        path("queries", QueriesView, name="queries"),
        path("boom", BoomView, name="boom"),
    ]
