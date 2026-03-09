"""
System tests for database connection lifecycle through the request pipeline.

These tests use the test Client to make real HTTP requests through the full
middleware/signal/view pipeline and verify that database connections are
properly created, reused, and cleaned up via the ContextVar storage.

Unlike test_connection_isolation.py (which uses FakeConn and manipulates the
ContextVar directly), these tests exercise the real DatabaseConnection against
a real database.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from plain.http import Response
from plain.models.connections import _create_connection as _original_create_connection
from plain.models.connections import _db_conn, get_connection, has_connection
from plain.models.db import close_old_connections
from plain.models.postgres.wrapper import DatabaseConnection
from plain.runtime import settings
from plain.signals import request_finished, request_started
from plain.test import Client
from plain.urls import Router, path
from plain.urls.resolvers import _get_cached_resolver
from plain.views import ServerSentEvent, ServerSentEventsView, View


def _sync_db_query():
    """Sync helper that runs a DB query — used by async views via to_thread."""
    with get_connection().cursor() as cursor:
        cursor.execute("SELECT 1")
        return cursor.fetchone()[0]


class DBQueryView(View):
    """Sync view that executes a real DB query via get_connection()."""

    def get(self):
        return Response(str(_sync_db_query()))


class AsyncDBQueryView(View):
    """Async view that accesses the DB via asyncio.to_thread()."""

    async def get(self):
        result = await asyncio.to_thread(_sync_db_query)
        return Response(str(result))


class DBQuerySSEView(ServerSentEventsView):
    """SSE view that accesses the DB via asyncio.to_thread() during streaming."""

    async def stream(self):
        result = await asyncio.to_thread(_sync_db_query)
        yield ServerSentEvent(data=str(result))


class TestRouter(Router):
    namespace = ""
    urls = [
        path("db-query/", DBQueryView, name="db_query"),
        path("async-db-query/", AsyncDBQueryView, name="async_db_query"),
        path("sse-db-query/", DBQuerySSEView, name="sse_db_query"),
    ]


@pytest.fixture
def _unblock_cursor():
    """Restore the real cursor method (blocked by the autouse _db_disabled fixture)."""
    DatabaseConnection.cursor = getattr(DatabaseConnection, "_enabled_cursor")


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


def _fresh_client():
    """Create a Client with a fresh middleware chain."""
    client = Client(raise_request_exception=True)
    client.handler._middleware_chain = None
    client.handler.load_middleware()
    return client


class TestConnectionLifecycle:
    """Full request lifecycle tests for connection creation and reuse."""

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_single_request_creates_exactly_one_connection(self, setup_db):
        """A request should create exactly one DatabaseConnection, stored in the ContextVar."""
        assert not has_connection()

        create_count = 0

        def counting_create():
            nonlocal create_count
            create_count += 1
            return _original_create_connection()

        with patch("plain.models.connections._create_connection", counting_create):
            client = _fresh_client()
            response = client.get("/db-query/")

        assert response.status_code == 200
        assert response.content == b"1"
        assert create_count == 1, f"Expected 1 connection created, got {create_count}"
        assert isinstance(_db_conn.get(), DatabaseConnection)

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_multiple_requests_create_one_connection_total(self, setup_db):
        """Three sequential requests should create exactly one connection, reused across all."""
        create_count = 0

        def counting_create():
            nonlocal create_count
            create_count += 1
            return _original_create_connection()

        with patch("plain.models.connections._create_connection", counting_create):
            client = _fresh_client()

            response1 = client.get("/db-query/")
            assert response1.status_code == 200
            first_conn_id = id(_db_conn.get())

            response2 = client.get("/db-query/")
            assert response2.status_code == 200

            response3 = client.get("/db-query/")
            assert response3.status_code == 200

        assert create_count == 1, (
            f"Expected 1 connection for 3 requests, got {create_count}"
        )
        assert id(_db_conn.get()) == first_conn_id, (
            "All requests should use the same connection object"
        )

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_close_old_connections_with_contextvar(self, setup_db):
        """
        With close_old_connections signals connected, the connection lifecycle
        works correctly with ContextVar storage: connections are kept alive
        within CONN_MAX_AGE and reused across requests.
        """
        create_count = 0

        def counting_create():
            nonlocal create_count
            create_count += 1
            return _original_create_connection()

        request_started.connect(close_old_connections)
        request_finished.connect(close_old_connections)
        try:
            with patch("plain.models.connections._create_connection", counting_create):
                client = _fresh_client()

                response1 = client.get("/db-query/")
                assert response1.status_code == 200

                # CONN_MAX_AGE=600s — connection stays alive
                conn = _db_conn.get()
                assert conn is not None
                assert conn.connection is not None, (
                    "Connection should be alive within CONN_MAX_AGE"
                )

                # Second request — close_old_connections on request_started
                # checks the connection, keeps it, view reuses it
                response2 = client.get("/db-query/")
                assert response2.status_code == 200

            assert create_count == 1, (
                f"Expected 1 connection with signals connected, got {create_count}"
            )
        finally:
            request_started.disconnect(close_old_connections)
            request_finished.disconnect(close_old_connections)

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_view_and_signals_see_same_contextvar(self, setup_db):
        """
        The request_started signal, view, and request_finished signal all
        run on the same thread and see the same ContextVar — verifying the
        ContextVar replaces threading.local() correctly for the sync path.
        """
        seen_connections: list[int | None] = []

        def track_connection(**kwargs):
            if has_connection():
                seen_connections.append(id(_db_conn.get()))
            else:
                seen_connections.append(None)

        request_started.connect(track_connection)
        request_finished.connect(track_connection)
        try:
            client = _fresh_client()
            response = client.get("/db-query/")
            assert response.status_code == 200

            assert len(seen_connections) == 2

            # request_started fires before the view — no connection yet
            assert seen_connections[0] is None

            # request_finished fires after the view — connection exists
            assert seen_connections[1] is not None

            # The connection seen by request_finished is the same one
            # still in the ContextVar
            assert seen_connections[1] == id(_db_conn.get())
        finally:
            request_started.disconnect(track_connection)
            request_finished.disconnect(track_connection)


class TestAsyncViewConnectionLifecycle:
    """Connection lifecycle tests for async views (including SSE)."""

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_async_view_db_access_via_to_thread(self, setup_db):
        """
        An async view that accesses the DB via asyncio.to_thread() should
        work correctly — to_thread propagates the ContextVar context.
        """
        create_count = 0

        def counting_create():
            nonlocal create_count
            create_count += 1
            return _original_create_connection()

        with patch("plain.models.connections._create_connection", counting_create):
            client = _fresh_client()
            response = client.get("/async-db-query/")

        assert response.status_code == 200
        assert response.content == b"1"
        assert create_count == 1, (
            f"Async view should create exactly 1 connection, got {create_count}"
        )

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_sse_view_db_access_via_to_thread(self, setup_db):
        """
        An SSE view that accesses the DB via asyncio.to_thread() during
        streaming should work correctly.
        """
        create_count = 0

        def counting_create():
            nonlocal create_count
            create_count += 1
            return _original_create_connection()

        with patch("plain.models.connections._create_connection", counting_create):
            client = _fresh_client()
            response = client.get("/sse-db-query/")

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["Content-Type"]
        assert "data: 1\n\n" in response.content.decode()
        assert create_count == 1, (
            f"SSE view should create exactly 1 connection, got {create_count}"
        )

    @pytest.mark.usefixtures("_unblock_cursor", "_clean_connection", "_test_router")
    def test_async_view_connection_stays_on_worker_thread(self, setup_db):
        """
        For async views using to_thread(), the DB connection is created on
        the worker thread's ContextVar — it does NOT propagate back to the
        calling context. This is correct: each thread owns its connection.

        request_started and request_finished both fire on the calling thread,
        which never had a connection. close_old_connections handles this
        gracefully (it's a no-op when has_connection() is False).
        """
        seen_connections: list[int | None] = []

        def track_connection(**kwargs):
            if has_connection():
                seen_connections.append(id(_db_conn.get()))
            else:
                seen_connections.append(None)

        request_started.connect(track_connection)
        request_finished.connect(track_connection)
        try:
            client = _fresh_client()
            response = client.get("/async-db-query/")
            assert response.status_code == 200

            assert len(seen_connections) == 2
            # Both signals fire on the calling thread — neither sees the
            # connection that was created on the to_thread worker
            assert seen_connections[0] is None
            assert seen_connections[1] is None
        finally:
            request_started.disconnect(track_connection)
            request_finished.disconnect(track_connection)
