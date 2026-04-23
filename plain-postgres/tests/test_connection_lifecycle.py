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

from __future__ import annotations

import asyncio
import concurrent.futures
from contextlib import contextmanager
from unittest.mock import patch

import pytest

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
from plain.test import Client, RequestFactory
from plain.urls import Router, path
from plain.urls.resolvers import _get_cached_resolver
from plain.views import ServerSentEvent, ServerSentEventsView, View


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


class TestRouter(Router):
    namespace = ""
    urls = [
        path("db-query/", DBQueryView, name="db_query"),
        path("async-db-query/", AsyncDBQueryView, name="async_db_query"),
        path("sse-db-query/", DBQuerySSEView, name="sse_db_query"),
        path("streaming-db-query/", StreamingDBQueryView, name="streaming_db_query"),
    ]


_tracking_seen: list[int | None] = []


class _ContextVarTrackingMiddleware(DatabaseConnectionMiddleware):
    def after_response(self, request, response):
        conn = _db_conn.get()
        _tracking_seen.append(id(conn) if conn is not None else None)
        return super().after_response(request, response)


@pytest.fixture
def _clean_connection():
    """Ensure the ContextVar starts empty and clean up any connection afterward."""
    token = _db_conn.set(None)
    yield
    # Close the connection on this thread (if any)
    conn = _db_conn.get()
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _db_conn.reset(token)

    # Async views create connections on worker threads (via asyncio.to_thread)
    # that we can't reach from this thread. Terminate them from PostgreSQL so
    # they don't block session teardown (DROP DATABASE).
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


@pytest.fixture
def _test_router():
    """Point the URL resolver at our minimal test router."""
    original = settings.URLS_ROUTER
    settings.URLS_ROUTER = "test_connection_lifecycle.TestRouter"
    _get_cached_resolver.cache_clear()
    yield
    settings.URLS_ROUTER = original
    _get_cached_resolver.cache_clear()


@pytest.fixture
def _with_db_middleware():
    """Insert `DatabaseConnectionMiddleware` at the top of MIDDLEWARE."""
    path = "plain.postgres.DatabaseConnectionMiddleware"
    original = list(settings.MIDDLEWARE)
    if path not in original:
        settings.MIDDLEWARE = [path] + original
    yield
    settings.MIDDLEWARE = original


def _fresh_client():
    """Create a Client with a fresh middleware chain."""
    client = Client(raise_request_exception=True)
    client.handler._middleware_chain = None
    client.handler.load_middleware()
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

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_single_request_creates_exactly_one_connection(self, setup_db):
        """A request should create exactly one DatabaseConnection, stored in the ContextVar."""
        assert not has_connection()

        with _patched_init_counter() as count:
            client = _fresh_client()
            response = client.get("/db-query/")

        assert response.status_code == 200
        assert response.content == b"1"
        assert count[0] == 1, f"Expected 1 connection created, got {count[0]}"
        assert isinstance(_db_conn.get(), DatabaseConnection)

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_multiple_requests_create_one_connection_total(self, setup_db):
        """Three sequential requests should create exactly one connection, reused across all."""
        with _patched_init_counter() as count:
            client = _fresh_client()

            response1 = client.get("/db-query/")
            assert response1.status_code == 200
            first_conn_id = id(_db_conn.get())

            response2 = client.get("/db-query/")
            assert response2.status_code == 200

            response3 = client.get("/db-query/")
            assert response3.status_code == 200

        assert count[0] == 1, f"Expected 1 connection for 3 requests, got {count[0]}"
        assert id(_db_conn.get()) == first_conn_id, (
            "All requests should use the same connection object"
        )

    @pytest.mark.usefixtures(
        "_unblock_cursor",
        "_clean_connection",
        "_test_router",
        "_with_db_middleware",
    )
    def test_middleware_returns_connection_between_requests(self, setup_db):
        """
        With `DatabaseConnectionMiddleware` installed, the wrapper persists
        in the ContextVar across requests but its underlying psycopg
        connection is returned to the pool between requests.
        """
        with _patched_init_counter() as count:
            client = _fresh_client()

            response1 = client.get("/db-query/")
            assert response1.status_code == 200

            # Wrapper persists; inner connection was returned to the pool.
            conn = _db_conn.get()
            assert conn is not None
            assert conn.connection is None, (
                "Inner psycopg connection should be returned to pool between requests"
            )

            # Second request: same wrapper, checks out a connection, returns it.
            response2 = client.get("/db-query/")
            assert response2.status_code == 200
            assert conn is _db_conn.get()

        assert count[0] == 1, f"Expected 1 wrapper across requests, got {count[0]}"

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_middleware_after_response_sees_view_connection(self, setup_db):
        """
        `after_response` runs on the same thread as the view, so it sees
        the ContextVar-backed DB connection the view just used.
        """
        _tracking_seen.clear()
        original = list(settings.MIDDLEWARE)
        settings.MIDDLEWARE = [
            "test_connection_lifecycle._ContextVarTrackingMiddleware"
        ] + original
        try:
            client = _fresh_client()
            response = client.get("/db-query/")
            assert response.status_code == 200

            assert len(_tracking_seen) == 1
            assert _tracking_seen[0] is not None
            assert _tracking_seen[0] == id(_db_conn.get())
        finally:
            settings.MIDDLEWARE = original


class TestAsyncViewConnectionLifecycle:
    """Connection lifecycle tests for async views (including SSE)."""

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_async_view_db_access_via_to_thread(self, setup_db):
        """
        An async view that accesses the DB via asyncio.to_thread() should
        work correctly — to_thread propagates the ContextVar context.
        """
        with _patched_init_counter() as count:
            client = _fresh_client()
            response = client.get("/async-db-query/")

        assert response.status_code == 200
        assert response.content == b"1"
        assert count[0] == 1, (
            f"Async view should create exactly 1 connection, got {count[0]}"
        )

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_sse_view_db_access_via_to_thread(self, setup_db):
        """
        An SSE view that accesses the DB via asyncio.to_thread() during
        streaming should work correctly.
        """
        with _patched_init_counter() as count:
            client = _fresh_client()
            response = client.get("/sse-db-query/")

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["Content-Type"]
        assert "data: 1\n\n" in response.content.decode()
        assert count[0] == 1, (
            f"SSE view should create exactly 1 connection, got {count[0]}"
        )


class TestStreamingResponseCleanup:
    """Streaming responses must return their DB connection once drained."""

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_streaming_connection_returned_after_body_drains(self, setup_db):
        """
        Drive `handler.handle()` directly so the per-request ContextVar
        boundary actually fires. The view opens a DB connection
        in-request, then returns a StreamingResponse. Middleware must
        capture the wrapper at `after_response` time (inside request_ctx)
        and hand it to a closer — looking up `_db_conn.get()` lazily at
        `response.close()` time would miss it because `close()` runs
        outside request_ctx.

        Asserts: the closer is called with the captured wrapper, and
        the wrapper's psycopg connection is released to the pool.
        """
        calls: list[DatabaseConnection | None] = []
        original_return = plain.postgres.middleware.return_database_connection

        def tracking_return(conn: DatabaseConnection | None = None) -> None:
            calls.append(conn)
            original_return(conn)

        original_middleware = list(settings.MIDDLEWARE)
        settings.MIDDLEWARE = [
            "plain.postgres.DatabaseConnectionMiddleware",
            *original_middleware,
        ]
        try:
            with patch.object(
                plain.postgres.middleware,
                "return_database_connection",
                tracking_return,
            ):
                handler = BaseHandler()
                handler.load_middleware()
                request = RequestFactory().get("/streaming-db-query/")

                async def run() -> Response:
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=2
                    ) as executor:
                        return await handler.handle(request, executor)

                response = asyncio.run(run())
                assert response.status_code == 200
                assert isinstance(response, StreamingResponse)

                # Streaming path: no close at after_response time.
                assert calls == []

                # Drain the body and close — that fires the resource closer.
                body = b"".join(response)
                assert body == b"streaming-chunk"
                response.close()

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
        finally:
            settings.MIDDLEWARE = original_middleware
