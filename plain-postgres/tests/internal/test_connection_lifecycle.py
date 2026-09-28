"""
System tests for database connection lifecycle through the request pipeline.

These tests use the test Client to make real HTTP requests through the full
middleware pipeline and verify that database connections are properly
created, reused, and cleaned up via the ContextVar storage and
`DatabaseConnectionMiddleware`.

Unlike test_connection_isolation.py (which uses FakeConn and manipulates the
ContextVar directly), these tests exercise the real DatabaseConnection against
a real database.
"""

import asyncio
import concurrent.futures
from contextlib import contextmanager
from unittest.mock import patch

import plain.postgres.middleware
from plain.http import Response, StreamingResponse
from plain.internal.handlers.base import BaseHandler
from plain.postgres.connection import DatabaseConnection
from plain.postgres.db import (
    _db_conn,
    get_connection,
    has_connection,
)
from plain.postgres.middleware import DatabaseConnectionMiddleware
from plain.runtime import settings
from plain.test import Client, build_request, override_settings
from plain.urls import Router, path
from plain.urls.resolvers import _get_cached_resolver
from plain.views import ServerSentEvent, ServerSentEventsView, View
from postgres_test_helpers import clean_connection


def _sync_db_query():
    """Sync helper that runs a DB query — used by async views via to_thread."""
    with get_connection().cursor() as cursor:
        cursor.execute("SELECT 1")
        row = cursor.fetchone()
        assert row is not None
        return row[0]


class DBQueryView(View):
    """Sync view that executes a real DB query via get_connection()."""

    def get(self):
        return Response(str(_sync_db_query()))


class AsyncDBQueryView(View):
    """Async view that accesses the DB via asyncio.to_thread()."""

    async def get(self) -> Response:  # ty: ignore[invalid-method-override]
        result = await asyncio.to_thread(_sync_db_query)
        return Response(str(result))


class DBQuerySSEView(ServerSentEventsView):
    """SSE view that accesses the DB via asyncio.to_thread() during streaming."""

    async def stream(self):
        result = await asyncio.to_thread(_sync_db_query)
        yield ServerSentEvent(data=str(result))


class StreamingDBQueryView(View):
    """Touches the DB in-request, then returns a StreamingResponse.

    The view runs a query so the wrapper exists (with a checked-out
    psycopg connection) *inside* the per-request ContextVar context
    when middleware's `after_response` runs. The streaming body itself
    yields static bytes — the test is about whether the wrapper the
    middleware captured gets closed when the body drains, not about DB
    access during streaming.
    """

    def get(self):
        _sync_db_query()

        def generate():
            yield b"streaming-chunk"

        return StreamingResponse(generate())


# (view's wrapper, body's wrapper) for each StreamingLazyQueryView request.
_lazy_query_wrappers: list[tuple[DatabaseConnection, DatabaseConnection]] = []


class StreamingLazyQueryView(View):
    """Queries only from its streaming body — the lazy-export shape.

    The body runs after the view returns. Run anywhere but the request's
    context, its `get_connection()` makes a wrapper of its own that the
    request's cleanup never returns.
    """

    def get(self):
        view_wrapper = get_connection()

        def generate():
            body_wrapper = get_connection()
            _lazy_query_wrappers.append((view_wrapper, body_wrapper))
            with body_wrapper.cursor() as cursor:
                cursor.execute("SELECT 1")
            yield b"lazy-chunk"

        return StreamingResponse(generate())


class WebSocketDBQueryView(View):
    """Queries only inside the socket, from a thread — a copied context."""

    async def websocket(self, ws) -> None:
        result = await asyncio.to_thread(_sync_db_query)
        await ws.send(str(result))


class HandshakeDBWebSocketView(View):
    """Queries during the handshake, then reports the wrapper's state
    from inside the socket and queries again."""

    def before_request(self) -> None:
        _sync_db_query()

    async def websocket(self, ws) -> None:
        conn = _db_conn.get()
        assert conn is not None
        held = "held" if conn.connection is not None else "returned"
        await ws.send(held)
        await ws.send(str(await asyncio.to_thread(_sync_db_query)))


class TestRouter(Router):
    namespace = ""
    urls = (
        path("db-query", DBQueryView, name="db_query"),
        path("async-db-query", AsyncDBQueryView, name="async_db_query"),
        path("sse-db-query", DBQuerySSEView, name="sse_db_query"),
        path("streaming-db-query", StreamingDBQueryView, name="streaming_db_query"),
        path("streaming-lazy-query", StreamingLazyQueryView, name="streaming_lazy"),
        path("ws-db-query", WebSocketDBQueryView, name="ws_db_query"),
        path("ws-handshake-db", HandshakeDBWebSocketView, name="ws_handshake_db"),
    )


_tracking_seen: list[int | None] = []


class _ContextVarTrackingMiddleware(DatabaseConnectionMiddleware):
    def after_response(self, request, response):
        conn = _db_conn.get()
        _tracking_seen.append(id(conn) if conn is not None else None)
        return super().after_response(request, response)


@contextmanager
def _clean_connection():
    """Ensure the ContextVar starts empty and clean up any connection afterward."""
    with clean_connection():
        yield

    # Async views create connections on worker threads (via asyncio.to_thread)
    # that we can't reach from this thread. Terminate them from PostgreSQL so
    # they don't block worker teardown (DROP DATABASE).
    if has_connection():
        try:
            with get_connection().cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid != pg_backend_pid()"
                )
        except Exception:
            pass


@contextmanager
def _test_router():
    """Point the URL resolver at our minimal test router."""
    _get_cached_resolver.cache_clear()
    try:
        with override_settings(URLS_ROUTER=f"{__name__}.TestRouter"):
            yield
    finally:
        _get_cached_resolver.cache_clear()


@contextmanager
def _with_db_middleware():
    """Insert `DatabaseConnectionMiddleware` at the top of MIDDLEWARE."""
    middleware_path = "plain.postgres.DatabaseConnectionMiddleware"
    middleware = list(settings.MIDDLEWARE)
    if middleware_path not in middleware:
        middleware = [middleware_path] + middleware
    with override_settings(MIDDLEWARE=middleware):
        yield


def _fresh_client():
    """A new Client, which builds its middleware chain at its first request."""
    client = Client(raise_exceptions=True)
    return client


@contextmanager
def _patched_init_counter():
    """Patch DatabaseConnection.__init__ to count instantiations."""
    count = [0]
    original = DatabaseConnection.__init__

    def counting(self, *args, **kwargs):
        count[0] += 1
        original(self, *args, **kwargs)

    with patch.object(DatabaseConnection, "__init__", counting):
        yield count


class TestConnectionLifecycle:
    """Full request lifecycle tests for connection creation and reuse."""

    def test_single_request_creates_exactly_one_connection(self):
        """A request should create exactly one DatabaseConnection, stored in the ContextVar."""
        with _clean_connection(), _test_router():
            assert not has_connection()

            with _patched_init_counter() as count:
                client = _fresh_client()
                response = client.get("/db-query")

            assert response.status_code == 200
            assert response.body == b"1"
            assert count[0] == 1, f"Expected 1 connection created, got {count[0]}"
            assert isinstance(_db_conn.get(), DatabaseConnection)

    def test_multiple_requests_create_one_connection_total(self):
        """Three sequential requests should create exactly one connection, reused across all."""
        with _clean_connection(), _test_router():
            with _patched_init_counter() as count:
                client = _fresh_client()

                response1 = client.get("/db-query")
                assert response1.status_code == 200
                first_conn_id = id(_db_conn.get())

                response2 = client.get("/db-query")
                assert response2.status_code == 200

                response3 = client.get("/db-query")
                assert response3.status_code == 200

            assert count[0] == 1, (
                f"Expected 1 connection for 3 requests, got {count[0]}"
            )
            assert id(_db_conn.get()) == first_conn_id, (
                "All requests should use the same connection object"
            )

    def test_middleware_returns_connection_between_requests(self):
        """
        With `DatabaseConnectionMiddleware` installed, the wrapper persists
        in the ContextVar across requests but its underlying psycopg
        connection is returned to the pool between requests.
        """
        with _clean_connection(), _test_router(), _with_db_middleware():
            with _patched_init_counter() as count:
                client = _fresh_client()

                response1 = client.get("/db-query")
                assert response1.status_code == 200

                # Wrapper persists; inner connection was returned to the pool.
                conn = _db_conn.get()
                assert conn is not None
                assert conn.connection is None, (
                    "Inner psycopg connection should be returned to pool between requests"
                )

                # Second request: same wrapper, checks out a connection, returns it.
                response2 = client.get("/db-query")
                assert response2.status_code == 200
                assert conn is _db_conn.get()

            assert count[0] == 1, f"Expected 1 wrapper across requests, got {count[0]}"

    def test_middleware_after_response_sees_view_connection(self):
        """
        `after_response` runs on the same thread as the view, so it sees
        the ContextVar-backed DB connection the view just used.
        """
        with _clean_connection(), _test_router():
            _tracking_seen.clear()
            middleware = [f"{__name__}._ContextVarTrackingMiddleware"] + list(
                settings.MIDDLEWARE
            )
            with override_settings(MIDDLEWARE=middleware):
                client = _fresh_client()
                response = client.get("/db-query")
                assert response.status_code == 200

                assert len(_tracking_seen) == 1
                assert _tracking_seen[0] is not None
                assert _tracking_seen[0] == id(_db_conn.get())


class TestAsyncViewConnectionLifecycle:
    """Connection lifecycle tests for async views (including SSE)."""

    def test_async_view_db_access_via_to_thread(self):
        """
        An async view that accesses the DB via asyncio.to_thread() should
        work correctly — to_thread propagates the ContextVar context.
        """
        with _clean_connection(), _test_router():
            with _patched_init_counter() as count:
                client = _fresh_client()
                response = client.get("/async-db-query")

            assert response.status_code == 200
            assert response.body == b"1"
            assert count[0] == 1, (
                f"Async view should create exactly 1 connection, got {count[0]}"
            )

    def test_sse_view_db_access_via_to_thread(self):
        """
        An SSE view that accesses the DB via asyncio.to_thread() during
        streaming should work correctly.
        """
        with _clean_connection(), _test_router():
            with _patched_init_counter() as count:
                client = _fresh_client()
                response = client.get("/sse-db-query")

            assert response.status_code == 200
            assert "text/event-stream" in response.headers["Content-Type"]
            assert "data: 1\n\n" in response.text
            assert count[0] == 1, (
                f"SSE view should create exactly 1 connection, got {count[0]}"
            )


class TestStreamingResponseCleanup:
    """Streaming responses must return their DB connection once drained."""

    def test_streaming_connection_returned_after_body_drains(self):
        """
        Drive `handler.handle()` directly, then send the body the way the
        server does, so the per-request ContextVar boundary actually
        fires. The view opens a DB connection in-request, then returns a
        StreamingResponse. Middleware captures the wrapper at
        `after_response` time (inside request_ctx) and hands it to a
        closer, which runs once the body is sent.

        Asserts: the closer is called with the captured wrapper, and
        the wrapper's psycopg connection is released to the pool.
        """
        with _clean_connection(), _test_router():
            calls: list[DatabaseConnection | None] = []
            original_return = plain.postgres.middleware.return_database_connection

            def tracking_return(conn: DatabaseConnection | None = None) -> None:
                calls.append(conn)
                original_return(conn)

            middleware = [
                "plain.postgres.DatabaseConnectionMiddleware",
                *settings.MIDDLEWARE,
            ]
            with (
                override_settings(MIDDLEWARE=middleware),
                patch.object(
                    plain.postgres.middleware,
                    "return_database_connection",
                    tracking_return,
                ),
            ):
                handler = BaseHandler()
                handler.load_middleware()
                request = build_request("GET", "/streaming-db-query")

                async def run() -> bytes:
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=2
                    ) as executor:
                        lifecycle = await handler.handle(request, executor)
                        response = lifecycle.response
                        assert response.status_code == 200
                        assert isinstance(response, StreamingResponse)

                        # Streaming path: no close at after_response time.
                        assert calls == []

                        chunks: list[bytes] = []

                        async def write() -> None:
                            async for chunk in lifecycle:
                                chunks.append(chunk)

                        # Sending the body closes the response after it —
                        # that fires the resource closer.
                        await lifecycle.send(write)
                        return b"".join(chunks)

                body = asyncio.run(run())
                assert body == b"streaming-chunk"

                # The closer ran exactly once and received the wrapper
                # captured during after_response.
                assert len(calls) == 1
                captured = calls[0]
                assert captured is not None, (
                    "Middleware failed to capture the wrapper at append time"
                )
                assert captured.connection is None, (
                    "Captured wrapper's psycopg connection should be returned"
                )

    def test_lazy_body_query_uses_the_views_connection(self):
        """A body that queries runs in the request's context, so it shares
        the view's wrapper — the one the middleware returns at the end —
        instead of checking out a connection nothing returns."""
        with _clean_connection(), _test_router(), _with_db_middleware():
            _lazy_query_wrappers.clear()
            handler = BaseHandler()
            handler.load_middleware()
            request = build_request("GET", "/streaming-lazy-query")

            async def run() -> bytes:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    lifecycle = await handler.handle(request, executor)
                    chunks: list[bytes] = []

                    async def write() -> None:
                        async for chunk in lifecycle:
                            chunks.append(chunk)

                    await lifecycle.send(write)
                    return b"".join(chunks)

            assert asyncio.run(run()) == b"lazy-chunk"

            [(view_wrapper, body_wrapper)] = _lazy_query_wrappers
            assert body_wrapper is view_wrapper
            assert view_wrapper.connection is None, (
                "The connection the body queried on should be back in the pool"
            )


class TestWebSocketConnectionLifecycle:
    """A websocket holds no database connection it is not using."""

    def test_socket_only_query_is_returned_when_the_socket_ends(self):
        with _clean_connection(), _test_router(), _with_db_middleware():
            calls: list[DatabaseConnection | None] = []
            original_return = plain.postgres.middleware.return_database_connection

            def tracking_return(conn: DatabaseConnection | None = None) -> None:
                calls.append(conn)
                original_return(conn)

            with (
                patch.object(
                    plain.postgres.middleware,
                    "return_database_connection",
                    tracking_return,
                ),
                _fresh_client().websocket("/ws-db-query") as ws,
            ):
                assert ws.receive() == "1"

            # Returned once at the handshake (a no-op on an unused wrapper) and
            # once by the closer when the socket ended; the same wrapper both
            # times, and the socket's query acquired through it — so it is
            # released now.
            assert len(calls) == 2
            assert calls[0] is calls[1]
            assert calls[0] is not None
            assert calls[0].connection is None

    def test_handshake_connection_is_returned_before_the_socket_starts(self):
        with (
            _clean_connection(),
            _test_router(),
            _with_db_middleware(),
            _fresh_client().websocket("/ws-handshake-db") as ws,
        ):
            assert ws.receive() == "returned"
            assert ws.receive() == "1"
