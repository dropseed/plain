from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
# design:
# An asyncio event loop runs all I/O (accept, TLS, read, write).
# A thread pool handles only application code (middleware + views).
#   New connection:
#     1. Accept (async) → wait readable (async) → TLS handshake (thread pool)
#     2. Read header bytes (async, until \r\n\r\n)
#     3. Parse headers from buffer (inline, no I/O)
#     4. Read body bytes (async, based on Content-Length or chunked)
#     5. Dispatch view (thread pool for sync, event loop for async)
#     6. Write response (async)
#   Keepalive waits use asyncio.wait_for with a timeout.
import asyncio
import errno
import logging
import os
import signal
import socket
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import FrameType
from typing import TYPE_CHECKING, Any

from plain.internal.reloader import Reloader

from .. import http, sock, util
from ..accesslog import log_access
from ..http.errors import (
    ConfigurationProblem,
    InvalidHeader,
    InvalidHeaderName,
    InvalidHostHeader,
    InvalidHTTPVersion,
    InvalidRequestLine,
    InvalidRequestMethod,
    LimitRequestHeaders,
    LimitRequestLine,
    ObsoleteFolding,
    UnsupportedTransferCoding,
)
from ..http.h2handler import async_handle_h2_connection
from ..http.message import LIMIT_REQUEST_FIELD_SIZE, LIMIT_REQUEST_FIELDS, Request
from ..http.response import Response, create_request
from ..http.unreader import AsyncBridgeUnreader, BufferUnreader
from .workertmp import WorkerHeartbeat

if TYPE_CHECKING:
    from ..app import ServerApplication


class _ParseError(Exception):
    """Raised for connection-level issues (EOF, disconnect) that don't need an error response."""


class _IncompleteBody(Exception):
    """Raised when the request body could not be fully read (timeout or disconnect)."""


class _BodyTooLarge(Exception):
    """Raised when a chunked body exceeds the pre-buffer limit.

    Carries the partial data so the caller can fall back to bridge mode.
    """

    def __init__(self, partial_data: bytes) -> None:
        self.partial_data = partial_data


# Keep-alive connection timeout in seconds
KEEPALIVE = 2

# Total time allowed for reading all headers (slowloris protection).
# Individual recv calls use KEEPALIVE as their timeout, but a client
# could send one byte every ~1.9s to stay under the per-recv limit.
# This bounds the total wall-clock time for the header phase.
HEADER_READ_TIMEOUT = 10

# Maximum total size of headers (request line + headers) in bytes.
# This bounds the async read loop to prevent slow/malicious clients
# from consuming unbounded memory.
MAX_HEADER_SIZE = LIMIT_REQUEST_FIELDS * (LIMIT_REQUEST_FIELD_SIZE + 2) + 4

SIGNALS = [
    signal.SIGABRT,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGINT,
    signal.SIGTERM,
    signal.SIGWINCH,
]


def _is_chunked_complete(data: bytes) -> bool:
    """Check if a chunked transfer-encoded body is complete.

    Properly parses chunk boundaries to avoid false matches in binary data.
    """
    pos = 0
    n = len(data)
    while pos < n:
        # Find \r\n after chunk size
        crlf = data.find(b"\r\n", pos)
        if crlf < 0:
            return False

        # Parse chunk size (hex, ignore extensions after semicolon)
        size_line = data[pos:crlf]
        semi = size_line.find(b";")
        if semi >= 0:
            size_line = size_line[:semi]

        try:
            chunk_size = int(size_line.strip(), 16)
        except ValueError:
            return False

        if chunk_size == 0:
            # Last chunk — need trailing \r\n (no trailers) or trailers + \r\n\r\n
            after_last = crlf + 2
            if after_last >= n:
                return False
            if data[after_last : after_last + 2] == b"\r\n":
                return True
            return data.find(b"\r\n\r\n", after_last) >= 0

        # Skip chunk data + \r\n
        next_pos = crlf + 2 + chunk_size + 2
        if next_pos > n:
            return False
        pos = next_pos

    return False


def _parse_body_headers(header_data: bytes) -> tuple[int, bool, bool]:
    """Extract Content-Length, Transfer-Encoding, and Expect from raw headers.

    Returns (content_length, is_chunked, expect_continue).
    content_length is -1 if not present or invalid.
    """
    content_length = -1
    is_chunked = False
    expect_continue = False

    header_str = header_data.decode("latin-1", errors="replace")
    lines = header_str.split("\r\n")
    for line in lines[1:]:  # skip request line
        if not line:
            break
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name_upper = name.strip().upper()
        if name_upper == "CONTENT-LENGTH":
            try:
                content_length = int(value.strip())
            except ValueError:
                content_length = -1
        elif name_upper == "TRANSFER-ENCODING":
            if "chunked" in value.lower():
                is_chunked = True
        elif name_upper == "EXPECT":
            if "100-continue" in value.lower():
                expect_continue = True

    # RFC 9112 §6.1: If both Content-Length and Transfer-Encoding are
    # present, Transfer-Encoding takes precedence. Ignore Content-Length
    # to ensure the body strategy (pre-buffer vs bridge) uses chunked reading.
    if is_chunked and content_length >= 0:
        content_length = -1

    return content_length, is_chunked, expect_continue


def check_worker_config(threads: int, connections: int, log: logging.Logger) -> None:
    max_keepalived = connections - threads

    if max_keepalived <= 0:
        log.warning(
            "No keepalived connections can be handled. "
            "Check the number of worker connections and threads."
        )


class TConn:
    def __init__(
        self,
        app: ServerApplication,
        sock: socket.socket,
        client: tuple[str, int],
        server: tuple[str, int],
    ) -> None:
        self.app = app
        self.sock = sock
        self.client = client
        self.server = server

        self.is_h2: bool = False
        self.is_ssl: bool = False
        self.handed_off: bool = False
        self.req_count: int = 0

        # Asyncio streams — set after TLS handshake via asyncio transport
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

        # Byte read during keepalive wait, prepended to next header read
        self._keepalive_byte: bytes = b""

        # set the socket to non blocking
        self.sock.setblocking(False)

    def close(self) -> None:
        if self.writer is not None:
            if not self.writer.is_closing():
                self.writer.close()
        else:
            util.close(self.sock)


async def _conn_recv(conn: TConn, n: int) -> bytes:
    """Read up to n bytes from a connection.

    Uses StreamReader when available (TLS connections), otherwise
    falls back to the raw socket via util.async_recv().
    """
    if conn.reader is not None:
        return await conn.reader.read(n)
    return await util.async_recv(conn.sock, n)


async def _conn_sendall(conn: TConn, data: bytes) -> None:
    """Send all bytes on a connection.

    Uses StreamWriter when available (TLS connections), otherwise
    falls back to the raw socket via util.async_sendall().
    """
    if conn.writer is not None:
        conn.writer.write(data)
        await conn.writer.drain()
        return
    await util.async_sendall(conn.sock, data)


async def _conn_write_error(
    conn: TConn, status_int: int, reason: str, mesg: str
) -> None:
    """Send an HTTP error response on a connection."""
    await _conn_sendall(conn, util._error_response_bytes(status_int, reason, mesg))


class Worker:
    def __init__(
        self,
        age: int,
        ppid: int,
        sockets: list[sock.BaseSocket],
        app: ServerApplication,
        timeout: int | float,
        heartbeat: WorkerHeartbeat,
        handler: Any,
    ):
        self.age = age
        self.pid: str | int = "[booting]"
        self.ppid = ppid
        self.sockets = sockets
        self.app = app
        self.timeout = timeout
        self.booted = False
        self.reloader: Any = None

        self.alive = True
        self.log = logging.getLogger("plain.server")
        self.heartbeat = heartbeat
        self.handler = handler

        from plain.runtime import settings

        self.max_connections: int = settings.SERVER_CONNECTIONS
        self.max_keepalived: int = self.max_connections - self.app.threads
        self.max_body: int = settings.DATA_UPLOAD_MAX_MEMORY_SIZE or (10 * 1024 * 1024)
        self.nr_conns: int = 0
        self._connection_tasks: set[asyncio.Task] = set()
        self._capacity_available: asyncio.Event = asyncio.Event()
        self._capacity_available.set()
        # Worker-level H2 stream budget — limits total in-flight H2 streams
        # across all connections to avoid overwhelming the thread pool.
        self._h2_stream_budget: asyncio.Semaphore = asyncio.Semaphore(
            self.app.threads * 4
        )

    def __str__(self) -> str:
        return f"<Worker {self.pid}>"

    def notify(self) -> None:
        self.heartbeat.notify()

    def init_process(self) -> None:
        # Thread pool — used only for application code (middleware + views)
        self.tpool: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=self.app.threads
        )

        # Reseed the random number generator
        util.seed()

        # Prevent listener sockets from leaking into subprocesses
        for s in self.sockets:
            util.close_on_exec(s.fileno())

        # Reset all signals to default before asyncio takes over
        for s in SIGNALS:
            signal.signal(s, signal.SIG_DFL)

        # start the reloader
        if self.app.reload:

            def changed(fname: str) -> None:
                self.log.debug("Server worker reloading: %s modified", fname)
                self.alive = False
                time.sleep(0.1)
                sys.exit(0)

            self.reloader = Reloader(callback=changed, watch_html=True)

        if self.reloader:
            self.reloader.start()

        # Enter main run loop
        self.booted = True
        asyncio.run(self.run())

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        # Signal handlers
        loop.add_signal_handler(signal.SIGTERM, self._signal_exit)
        loop.add_signal_handler(signal.SIGINT, self._signal_quit)
        loop.add_signal_handler(signal.SIGQUIT, self._signal_quit)
        # SIGABRT/SIGWINCH use signal.signal() because they need the
        # (sig, frame) signature and call sys.exit() directly
        signal.signal(signal.SIGABRT, self.handle_abort)
        signal.signal(signal.SIGWINCH, self.handle_winch)
        signal.siginterrupt(signal.SIGTERM, False)

        # Start accept loops (one task per listener)
        accept_tasks = []
        for listener in self.sockets:
            listener.setblocking(False)
            accept_tasks.append(loop.create_task(self._accept_loop(listener)))

        # Heartbeat loop
        while self.alive:
            self.notify()
            if not self.is_parent_alive():
                break
            # Surface accept-loop crashes instead of silently losing a listener
            for task in accept_tasks:
                if task.done() and not task.cancelled():
                    exc = task.exception()
                    if exc is not None:
                        self.log.error("Accept loop crashed: %s", exc)
                        self.alive = False
                        break
            await asyncio.sleep(1.0)

        # Cancel accept loops before closing listener sockets to avoid
        # EBADF from sock_accept on an already-closed socket
        for task in accept_tasks:
            task.cancel()
        await asyncio.gather(*accept_tasks, return_exceptions=True)

        await self._graceful_shutdown()

    async def _accept_loop(self, listener: sock.BaseSocket) -> None:
        loop = asyncio.get_running_loop()
        assert listener.sock is not None, "Listener socket is closed"
        listener_sock = listener.sock
        server: tuple[str, int] = listener_sock.getsockname()
        while self.alive:
            # Backpressure: wait when at capacity
            if self.nr_conns >= self.max_connections:
                self._capacity_available.clear()
                await self._capacity_available.wait()
                continue

            try:
                client_sock, client_addr = await loop.sock_accept(listener_sock)
            except OSError as e:
                if e.errno not in (
                    errno.EAGAIN,
                    errno.ECONNABORTED,
                    errno.EWOULDBLOCK,
                ):
                    raise
                continue

            conn = TConn(self.app, client_sock, client_addr, server)
            self.nr_conns += 1

            task = loop.create_task(self._handle_connection(conn))
            self._connection_tasks.add(task)
            task.add_done_callback(self._connection_tasks.discard)

    async def _handle_connection(self, conn: TConn) -> None:
        loop = asyncio.get_running_loop()
        try:
            # Wait for the socket to become readable before doing anything.
            # This prevents slow/idle clients from consuming resources.
            try:
                await asyncio.wait_for(
                    self._wait_readable(conn),
                    timeout=KEEPALIVE,
                )
            except TimeoutError:
                return

            # TLS handshake via asyncio transport layer.
            # Uses loop.start_tls() which gives asyncio ownership of SSL state
            # via memory BIO (ssl.SSLObject). This is required for reliable
            # async I/O on long-lived H2 connections — raw ssl.SSLSocket +
            # add_reader/add_writer silently loses data.
            if self.app.is_ssl:
                try:
                    conn.reader, conn.writer = await asyncio.wait_for(
                        self._async_tls_handshake(conn),
                        timeout=KEEPALIVE,
                    )
                except (ssl.SSLError, OSError) as e:
                    # asyncio took socket ownership via create_connection;
                    # it closes the transport on failure, so prevent
                    # conn.close() from double-closing the raw fd.
                    conn.handed_off = True
                    if isinstance(e, ssl.SSLError) and e.args[0] == ssl.SSL_ERROR_EOF:
                        self.log.debug("ssl connection closed during handshake")
                    else:
                        self.log.debug("TLS handshake failed: %s", e)
                    return
                except TimeoutError:
                    conn.handed_off = True
                    self.log.debug("TLS handshake timed out")
                    return
                conn.is_ssl = True

                ssl_object = conn.writer.get_extra_info("ssl_object")
                alpn = ssl_object.selected_alpn_protocol() if ssl_object else None

                if alpn == "h2":
                    conn.is_h2 = True
                    conn.handed_off = True
                    await async_handle_h2_connection(
                        conn.reader,
                        conn.writer,
                        conn.client,
                        conn.server,
                        self.handler,
                        self.app.is_ssl,
                        self.tpool,
                        stream_budget=self._h2_stream_budget,
                    )
                    return

            while self.alive:
                # Read HTTP headers asynchronously on the event loop
                try:
                    header_data, body_start = await self._async_read_headers(conn)
                except (TimeoutError, OSError):
                    break
                except LimitRequestHeaders as e:
                    await self._async_handle_error(None, conn, e)
                    break
                if not header_data:
                    break

                # Analyze headers to determine body handling strategy
                max_body = self.max_body
                content_length, is_chunked, expect_continue = _parse_body_headers(
                    header_data
                )

                if expect_continue:
                    try:
                        await _conn_sendall(conn, b"HTTP/1.1 100 Continue\r\n\r\n")
                    except OSError:
                        break

                # Large Content-Length bodies use the bridge for lazy streaming.
                # Small bodies and chunked are pre-buffered (with fallback to
                # bridge if a chunked body exceeds the pre-buffer limit).
                use_bridge = content_length > max_body

                if use_bridge:
                    unreader = AsyncBridgeUnreader(
                        header_data + body_start,
                        conn,
                        loop,
                        timeout=self.timeout,
                    )
                else:
                    try:
                        body_data = await self._async_read_body(
                            conn,
                            body_start,
                            content_length,
                            is_chunked,
                            max_body,
                        )
                    except _IncompleteBody:
                        await _conn_write_error(
                            conn,
                            408,
                            "Request Timeout",
                            "Incomplete request body",
                        )
                        break
                    except _BodyTooLarge as e:
                        # Chunked body exceeded pre-buffer limit — fall back
                        # to bridge mode with the partially-read data.
                        use_bridge = True
                        unreader = AsyncBridgeUnreader(
                            header_data + e.partial_data,
                            conn,
                            loop,
                            timeout=self.timeout,
                        )
                    else:
                        unreader = BufferUnreader(header_data + body_data)

                # Parse the request. For bridge unreaders, parsing runs in
                # the thread pool since the body reader may call chunk()
                # which bridges back to the event loop.
                try:
                    if use_bridge:
                        parse_result = await loop.run_in_executor(
                            self.tpool,
                            self._parse_request,
                            conn,
                            unreader,
                            True,
                        )
                    else:
                        parse_result = self._parse_request(conn, unreader)
                except _ParseError:
                    break
                except TimeoutError:
                    # Bridge body read timed out — send 408 (not 500)
                    await _conn_write_error(
                        conn,
                        408,
                        "Request Timeout",
                        "Body read timed out",
                    )
                    break
                except Exception as e:
                    await self._async_handle_error(None, conn, e)
                    break

                if parse_result is None:
                    break

                req, http_request, resp, request_start = parse_result
                conn.req_count += 1

                keepalive = await self._dispatch(
                    req, conn, http_request, resp, request_start
                )

                # For bridge connections with known Content-Length, drain
                # unread body data so the client receives the response
                # without TCP RST. Chunked-to-bridge fallback (content_length=-1)
                # can't drain by length; force_close=True ensures the
                # connection closes cleanly via Connection: close header.
                if use_bridge and content_length > 0:
                    remaining = (
                        content_length - len(body_start) - unreader.socket_bytes_read  # type: ignore[union-attr]
                    )
                    while remaining > 0:
                        try:
                            data = await asyncio.wait_for(
                                _conn_recv(conn, min(remaining, 65536)),
                                timeout=KEEPALIVE,
                            )
                        except (TimeoutError, OSError):
                            break
                        if not data:
                            break
                        remaining -= len(data)

                if not keepalive or not self.alive:
                    break

                # Wait for the next request (keepalive)
                try:
                    await asyncio.wait_for(
                        self._wait_readable(conn),
                        timeout=KEEPALIVE,
                    )
                except TimeoutError:
                    break
        finally:
            self.nr_conns -= 1
            if self.nr_conns < self.max_connections:
                self._capacity_available.set()
            if not conn.handed_off:
                conn.close()

    async def _async_tls_handshake(
        self, conn: TConn
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Perform TLS handshake via asyncio transport layer.

        Uses loop.create_connection() to wrap the raw socket in an asyncio
        transport, then loop.start_tls() to perform the handshake using
        asyncio's memory BIO (ssl.SSLObject). This avoids ssl.SSLSocket
        entirely, giving asyncio full control of the SSL state.
        """
        loop = asyncio.get_running_loop()
        assert conn.app.certfile is not None

        ssl_ctx = sock.ssl_context(conn.app.certfile, conn.app.keyfile)

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        # Wrap the accepted raw socket in an asyncio transport
        transport, _ = await loop.create_connection(lambda: protocol, sock=conn.sock)

        # Upgrade to TLS — asyncio uses ssl.SSLObject (memory BIO) internally
        new_transport = await loop.start_tls(
            transport, protocol, ssl_ctx, server_side=True
        )

        # Build the StreamWriter with the TLS-upgraded transport
        assert new_transport is not None
        writer = asyncio.StreamWriter(new_transport, protocol, reader, loop)

        return reader, writer

    async def _async_read_headers(self, conn: TConn) -> tuple[bytes, bytes]:
        """Read from the connection until the header delimiter \\r\\n\\r\\n.

        Returns (header_data, body_start) where body_start contains any
        bytes read past the header boundary.  Returns (b"", b"") on EOF.
        Raises LimitRequestHeaders if headers exceed MAX_HEADER_SIZE.
        Raises TimeoutError if total header read exceeds HEADER_READ_TIMEOUT.
        """
        buf = bytearray()
        # Prepend any byte consumed during keepalive wait
        if conn._keepalive_byte:
            buf.extend(conn._keepalive_byte)
            conn._keepalive_byte = b""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + HEADER_READ_TIMEOUT
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                self.log.debug(
                    "Header read exceeded total timeout (%ss)", HEADER_READ_TIMEOUT
                )
                raise TimeoutError("Header read timeout exceeded")
            try:
                data = await asyncio.wait_for(
                    _conn_recv(conn, 8192),
                    timeout=min(KEEPALIVE, remaining),
                )
            except TimeoutError:
                if buf:
                    self.log.debug("Slow client timed out during header read")
                raise
            if not data:
                return b"", b""

            buf.extend(data)

            idx = buf.find(b"\r\n\r\n")
            if idx >= 0:
                header_end = idx + 4
                return bytes(buf[:header_end]), bytes(buf[header_end:])

            if len(buf) > MAX_HEADER_SIZE:
                raise LimitRequestHeaders("Request headers exceeded max size")

    async def _async_read_body(
        self,
        conn: TConn,
        body_start: bytes,
        content_length: int,
        is_chunked: bool,
        max_body: int,
    ) -> bytes:
        """Pre-buffer the request body from the connection.

        Called for small bodies that fit in max_body. Header analysis and
        100-continue are handled by the caller.
        Returns the full body bytes. Raises _IncompleteBody on failure.
        """
        if content_length == 0 or (content_length < 0 and not is_chunked):
            return b""

        body = bytearray(body_start)

        if content_length > 0:
            remaining = content_length - len(body)
            while remaining > 0:
                try:
                    chunk = await asyncio.wait_for(
                        _conn_recv(conn, min(remaining, 65536)),
                        timeout=KEEPALIVE,
                    )
                except (TimeoutError, OSError):
                    raise _IncompleteBody(
                        f"Expected {content_length} bytes, got {len(body)}"
                    )
                if not chunk:
                    raise _IncompleteBody(
                        f"Expected {content_length} bytes, got {len(body)}"
                    )
                body.extend(chunk)
                remaining -= len(chunk)
            return bytes(body)

        if is_chunked:
            return await self._async_read_chunked_body(conn, body, max_body)

        return bytes(body)

    async def _async_read_chunked_body(
        self,
        conn: TConn,
        initial: bytearray,
        max_body: int,
    ) -> bytes:
        """Read a chunked transfer-encoded body asynchronously.

        Returns the raw chunked data (including chunk framing). The parser's
        ChunkedReader will decode it properly.
        Raises _IncompleteBody if the chunked message is not complete.
        Raises _BodyTooLarge if the body exceeds max_body (caller should
        fall back to bridge mode).
        """
        buf = initial

        # Check if initial data already contains the complete chunked body
        # (common when the entire request fits in one recv)
        if (
            len(buf) >= 5
            and buf[-4:] == b"\r\n\r\n"
            and _is_chunked_complete(bytes(buf))
        ):
            return bytes(buf)

        complete = False
        while len(buf) <= max_body:
            try:
                chunk = await asyncio.wait_for(
                    _conn_recv(conn, 65536),
                    timeout=KEEPALIVE,
                )
            except (TimeoutError, OSError):
                raise _IncompleteBody("Chunked body read timed out or disconnected")
            if not chunk:
                raise _IncompleteBody("Client disconnected during chunked body")
            buf.extend(chunk)

            # Only run the full parse when the buffer could contain the terminator
            if buf[-4:] == b"\r\n\r\n" and _is_chunked_complete(bytes(buf)):
                complete = True
                break

        if not complete:
            raise _BodyTooLarge(bytes(buf))

        return bytes(buf)

    async def _wait_readable(self, conn: TConn) -> None:
        # For asyncio stream connections, use a 1-byte read to wait for
        # data, then prepend it to the reader's buffer so it's not lost.
        if conn.reader is not None:
            data = await conn.reader.read(1)
            if data:
                # Prepend the peeked byte back into the buffer
                conn._keepalive_byte = data
            return

        s = conn.sock

        # SSL sockets may have decrypted data buffered internally that
        # won't trigger fd readability — check before waiting.
        if isinstance(s, ssl.SSLSocket) and s.pending() > 0:
            return

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()

        def _on_readable() -> None:
            if not fut.done():
                loop.remove_reader(s)
                fut.set_result(None)

        try:
            loop.add_reader(s, _on_readable)
        except OSError:
            # Socket already closed by client
            return
        try:
            await fut
        except asyncio.CancelledError:
            loop.remove_reader(s)
            raise

    async def _graceful_shutdown(self) -> None:
        # Close listener sockets
        for s in self.sockets:
            s.close()

        # Wait for in-flight connections with timeout
        if self._connection_tasks:
            from plain.runtime import settings

            timeout = settings.SERVER_GRACEFUL_TIMEOUT
            _, pending = await asyncio.wait(self._connection_tasks, timeout=timeout)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending)

        self.tpool.shutdown(wait=False)

    def _signal_exit(self) -> None:
        self.alive = False

    def _signal_quit(self) -> None:
        # Hard stop — the arbiter uses SIGQUIT for immediate termination.
        # Intentionally bypasses _graceful_shutdown.
        self.alive = False
        self.tpool.shutdown(wait=False, cancel_futures=True)
        sys.exit(0)

    def handle_abort(self, sig: int, frame: FrameType | None) -> None:
        self.alive = False
        self.tpool.shutdown(wait=False, cancel_futures=True)
        sys.exit(1)

    def handle_winch(self, sig: int, fname: Any) -> None:
        # Ignore SIGWINCH in worker. Fixes a crash on OpenBSD.
        self.log.debug("worker: SIGWINCH ignored.")

    async def _async_handle_error(
        self,
        req: Request | None,
        conn: TConn,
        exc: BaseException,
    ) -> None:
        """Handle request errors, sending an appropriate HTTP error response."""
        request_start = datetime.now()
        addr = conn.client or ("", -1)  # unix socket case
        if isinstance(
            exc,
            InvalidRequestLine
            | InvalidRequestMethod
            | InvalidHTTPVersion
            | InvalidHeader
            | InvalidHeaderName
            | InvalidHostHeader
            | LimitRequestLine
            | LimitRequestHeaders
            | UnsupportedTransferCoding
            | ConfigurationProblem
            | ObsoleteFolding
            | ssl.SSLError,
        ):
            status_int = 400
            reason = "Bad Request"

            if isinstance(exc, InvalidRequestLine):
                mesg = f"Invalid Request Line '{exc}'"
            elif isinstance(exc, InvalidRequestMethod):
                mesg = f"Invalid Method '{exc}'"
            elif isinstance(exc, InvalidHTTPVersion):
                mesg = f"Invalid HTTP Version '{exc}'"
            elif isinstance(exc, UnsupportedTransferCoding):
                mesg = str(exc)
                status_int = 501
            elif isinstance(exc, ConfigurationProblem):
                mesg = str(exc)
                status_int = 500
            elif isinstance(exc, ObsoleteFolding):
                mesg = str(exc)
            elif isinstance(exc, InvalidHostHeader):
                mesg = str(exc)
            elif isinstance(exc, InvalidHeaderName | InvalidHeader):
                mesg = str(exc)
                if not req and hasattr(exc, "req"):
                    req = exc.req  # type: ignore[assignment]  # for access log
            elif isinstance(exc, LimitRequestLine):
                mesg = str(exc)
            elif isinstance(exc, LimitRequestHeaders):
                reason = "Request Header Fields Too Large"
                mesg = f"Error parsing headers: '{exc}'"
                status_int = 431
            elif isinstance(exc, ssl.SSLError):
                reason = "Forbidden"
                mesg = f"'{exc}'"
                status_int = 403

            msg = "Invalid request from ip={ip}: {error}"
            self.log.warning(msg.format(ip=addr[0], error=str(exc)))
        else:
            if hasattr(req, "uri"):
                self.log.exception("Error handling request %s", req.uri)
            else:
                self.log.exception("Error handling request (no URI read)")
            status_int = 500
            reason = "Internal Server Error"
            mesg = ""

        if req is not None:
            request_time = datetime.now() - request_start
            resp = Response(req, conn.sock, is_ssl=conn.is_ssl, writer=conn.writer)
            resp.status = f"{status_int} {reason}"
            resp.response_length = len(mesg)
            log_access(resp, req, request_time)

        try:
            await _conn_write_error(conn, status_int, reason, mesg)
        except Exception:
            self.log.debug("Failed to send error message.")

    def is_parent_alive(self) -> bool:
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True

    def _parse_request(
        self,
        conn: TConn,
        unreader: BufferUnreader | AsyncBridgeUnreader,
        force_close: bool = False,
    ) -> tuple[Any, Any, Response, datetime] | None:
        """Parse an HTTP request from an unreader.

        Works with both BufferUnreader (pre-buffered) and AsyncBridgeUnreader
        (lazy streaming for large bodies).

        When force_close=True (bridge path), this runs in the thread pool.
        Body reads via chunk() bridge back to the event loop and are safe here.
        NOTE: Async views that read request.body on the event loop will
        deadlock with bridge connections because chunk() blocks the calling
        thread. This is an acceptable limitation — large uploads (> max_body)
        should use sync views. Increase DATA_UPLOAD_MAX_MEMORY_SIZE to avoid
        the bridge path if async body access is needed.

        Returns (req, http_request, resp, request_start) or None on EOF/close.
        Raises _ParseError for connection-level issues (EOF, disconnect).
        Lets HTTP protocol errors propagate so the caller can send
        async error responses.
        """
        try:
            req = Request(self.app.is_ssl, unreader, conn.client, conn.req_count + 1)

            if not req:
                return None

            request_start = datetime.now()

            # create_request sets _stream = req.body, which is the parser's
            # body reader — it properly decodes chunked/length-delimited data.
            http_request = create_request(req, conn.sock, conn.client, conn.server)

            resp = Response(req, conn.sock, is_ssl=self.app.is_ssl, writer=conn.writer)

            if force_close or not self.alive:
                resp.force_close()
            elif self.nr_conns >= self.max_keepalived:
                resp.force_close()

            return (req, http_request, resp, request_start)
        except http.errors.NoMoreData as e:
            self.log.debug("Ignored premature client disconnection. %s", e)
            raise _ParseError from e
        except StopIteration as e:
            self.log.debug("Closing connection. %s", e)
            raise _ParseError from e
        except OSError as e:
            if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.exception("Socket error processing request.")
            else:
                self.log.debug("Ignoring connection %s", e)
            raise _ParseError from e
        # HTTP protocol errors (InvalidRequestLine, InvalidHeader, etc.)
        # propagate to the caller for async error response handling.

    async def _async_finish_request(
        self,
        req: Any,
        resp: Response,
        http_response: Any,
        request_start: datetime,
    ) -> bool:
        """Write response using async I/O, log access, and determine keepalive."""
        try:
            await resp.async_write_response(http_response)
        finally:
            request_time = datetime.now() - request_start
            if http_response.log_access:
                log_access(resp, req, request_time)
            if hasattr(http_response, "close"):
                http_response.close()

        if resp.should_close():
            self.log.debug("Closing connection.")
            return False

        return True

    async def _async_handle_dispatch_error(
        self, req: Any, resp: Response, conn: TConn, exc: BaseException
    ) -> bool:
        """Handle exceptions from dispatch. Returns False (no keepalive)."""
        # TimeoutError is a subclass of OSError but isn't a socket error —
        # it's an app-level timeout (e.g., asyncio.wait_for in a view).
        # Send a 500 response instead of silently dropping the connection.
        if isinstance(exc, TimeoutError):
            if not resp.headers_sent:
                await self._async_handle_error(req, conn, exc)
            return False

        if isinstance(exc, OSError):
            if exc.errno in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.debug("Client disconnected during dispatch: %s", exc)
            else:
                self.log.exception("Socket error during dispatch.")
            return False

        if resp.headers_sent:
            self.log.exception("Error handling request")
            try:
                conn.close()
            except OSError:
                pass
        else:
            await self._async_handle_error(req, conn, exc)
        return False

    async def _dispatch(
        self,
        req: Any,
        conn: TConn,
        http_request: Any,
        resp: Response,
        request_start: datetime,
    ) -> bool:
        """Dispatch a request through the handler and write the response."""
        try:
            http_response = await self.handler.handle(http_request, self.tpool)

            # Check for async streaming response (SSE, etc.)
            from plain.http import AsyncStreamingResponse

            if isinstance(http_response, AsyncStreamingResponse):
                return await self._stream_async_response(
                    req, resp, http_response, request_start
                )

            # Write response using async I/O (no thread pool needed)
            return await self._async_finish_request(
                req, resp, http_response, request_start
            )
        except Exception as exc:
            return await self._async_handle_dispatch_error(req, resp, conn, exc)

    async def _stream_async_response(
        self,
        req: Any,
        resp: Response,
        http_response: Any,
        request_start: datetime,
    ) -> bool:
        """Stream an async response (SSE, etc.) chunk by chunk.

        Headers and chunks are written using async I/O. This keeps the
        event loop free between chunks and doesn't consume thread pool slots.
        """
        client_disconnected = False
        try:
            resp.prepare_response(http_response)
            await resp.async_send_headers()

            async for chunk in http_response:
                try:
                    await resp.async_write(chunk)
                except OSError:
                    client_disconnected = True
                    break
        finally:
            try:
                if hasattr(http_response, "aclose"):
                    await http_response.aclose()
            except Exception:
                self.log.debug("Error in aclose()")

            try:
                if not client_disconnected:
                    await resp.async_close()
            except OSError:
                pass
            finally:
                request_time = datetime.now() - request_start
                if http_response.log_access:
                    log_access(resp, req, request_time)
                if hasattr(http_response, "close"):
                    http_response.close()

        if client_disconnected or resp.should_close():
            return False
        return True
