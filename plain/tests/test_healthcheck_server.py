"""Tests for server-level health check handling.

The health check is handled at the server layer (event loop) before
dispatching to the thread pool. Tests are split into:

1. Unit tests for extract_request_path (pure function, no I/O)
2. Integration tests that start a real asyncio TCP server using the
   actual handle_connection code path, connect a real socket, and
   verify the response bytes.
"""

from __future__ import annotations

import asyncio
import logging
import socket

from plain.server.connection import Connection
from plain.server.http.h1 import extract_request_path, handle_connection

# ---------------------------------------------------------------------------
# Minimal worker stub — just the attributes handle_connection reads.
# No mocking framework, just a plain object.
# ---------------------------------------------------------------------------


class _StubWorker:
    def __init__(self, healthcheck_path: str = "") -> None:
        self.healthcheck_path_bytes = (
            healthcheck_path.encode("ascii") if healthcheck_path else b""
        )
        self.alive = True
        self.max_body = 10 * 1024 * 1024
        self.nr_conns = 0
        self.max_keepalived = 10
        self.log = logging.getLogger("test")
        self.tpool = None
        self.timeout = 5
        self.app = _StubApp()
        self.handler = None


# ---------------------------------------------------------------------------
# Helpers to spin up a real TCP server using handle_connection
# ---------------------------------------------------------------------------


class _StubApp:
    """Minimal stand-in for ServerApplication."""

    is_ssl = False


async def _start_healthcheck_server(
    healthcheck_path: str,
) -> tuple[asyncio.Server, int]:
    """Start a TCP server that runs handle_connection for each client."""
    worker = _StubWorker(healthcheck_path=healthcheck_path)

    async def on_connect(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        conn = Connection(
            worker.app,  # type: ignore[arg-type]
            reader,
            writer,
            client=("127.0.0.1", 0),
            server=("127.0.0.1", 0),
        )
        try:
            await handle_connection(worker, conn)  # type: ignore[arg-type]
        finally:
            conn.close()
            await asyncio.sleep(0)  # let the writer flush

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


def _send_request(port: int, raw_request: bytes) -> bytes:
    """Send a raw HTTP request and read the full response (blocks)."""
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    try:
        s.sendall(raw_request)
        # Health check closes the connection, so read until EOF.
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Unit tests: extract_request_path
# ---------------------------------------------------------------------------


class TestExtractRequestPath:
    """Unit tests for the pure path-extraction function used by the health check."""

    def test_simple_get(self):
        assert (
            extract_request_path(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
            == b"/health"
        )

    def test_strips_query_string(self):
        assert (
            extract_request_path(b"GET /health?ok=1 HTTP/1.1\r\nHost: x\r\n\r\n")
            == b"/health"
        )

    def test_root_path(self):
        assert extract_request_path(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n") == b"/"

    def test_deep_path(self):
        assert (
            extract_request_path(b"GET /a/b/c HTTP/1.1\r\nHost: x\r\n\r\n") == b"/a/b/c"
        )

    def test_post_method(self):
        assert (
            extract_request_path(b"POST /submit HTTP/1.1\r\nHost: x\r\n\r\n")
            == b"/submit"
        )

    def test_empty_data(self):
        assert extract_request_path(b"") == b""

    def test_malformed_no_space(self):
        assert extract_request_path(b"BADREQUEST\r\n\r\n") == b""

    def test_no_crlf(self):
        assert extract_request_path(b"GET /ok HTTP/1.1") == b""


# ---------------------------------------------------------------------------
# Integration tests: real TCP server with handle_connection
# ---------------------------------------------------------------------------


class TestHealthCheckIntegration:
    """Start a real asyncio TCP server and verify health check responses over the wire."""

    def test_healthcheck_returns_200_ok(self):
        async def _run() -> bytes:
            server, port = await _start_healthcheck_server("/_health")
            async with server:
                return await asyncio.to_thread(
                    _send_request,
                    port,
                    b"GET /_health HTTP/1.1\r\nHost: localhost\r\n\r\n",
                )

        resp = asyncio.run(_run())
        assert b"HTTP/1.1 200 OK" in resp
        assert b"Content-Type: text/plain" in resp
        assert resp.endswith(b"ok")

    def test_healthcheck_ignores_query_string(self):
        async def _run() -> bytes:
            server, port = await _start_healthcheck_server("/_health")
            async with server:
                return await asyncio.to_thread(
                    _send_request,
                    port,
                    b"GET /_health?ready=1 HTTP/1.1\r\nHost: localhost\r\n\r\n",
                )

        resp = asyncio.run(_run())
        assert b"HTTP/1.1 200 OK" in resp

    def test_non_healthcheck_path_not_intercepted(self):
        """A request to a different path should NOT get the health check response."""

        async def _run() -> bytes:
            server, port = await _start_healthcheck_server("/_health")
            async with server:
                return await asyncio.to_thread(
                    _send_request,
                    port,
                    b"GET /other HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
                )

        resp = asyncio.run(_run())
        # /other proceeds into the normal pipeline where the stub worker
        # has no handler — it will error or close. The key assertion is
        # that it does NOT return the health check response.
        assert b"HTTP/1.1 200 OK\r\n" not in resp

    def test_disabled_when_path_empty(self):
        """When healthcheck_path is empty, /_health is not intercepted."""

        async def _run() -> bytes:
            server, port = await _start_healthcheck_server("")
            async with server:
                return await asyncio.to_thread(
                    _send_request,
                    port,
                    b"GET /_health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
                )

        resp = asyncio.run(_run())
        assert b"HTTP/1.1 200 OK\r\n" not in resp
