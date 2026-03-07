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
import io
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
from ..http.unreader import BufferUnreader
from .workertmp import WorkerHeartbeat

if TYPE_CHECKING:
    from ..app import ServerApplication


class _ParseError(Exception):
    """Raised by _parse_buffered_request when an error response was sent."""


# Keep-alive connection timeout in seconds
KEEPALIVE = 2

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

        # set the socket to non blocking
        self.sock.setblocking(False)

    def close(self) -> None:
        util.close(self.sock)


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
        self.nr_conns: int = 0
        self._connection_tasks: set[asyncio.Task] = set()
        self._capacity_available: asyncio.Event = asyncio.Event()
        self._capacity_available.set()

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
                    self._wait_readable(conn.sock),
                    timeout=KEEPALIVE,
                )
            except TimeoutError:
                return

            # TLS handshake (requires blocking mode, so use thread pool briefly)
            if self.app.is_ssl:
                try:
                    conn.sock = await loop.run_in_executor(
                        self.tpool, self._do_tls_handshake, conn
                    )
                except (ssl.SSLError, OSError) as e:
                    if isinstance(e, ssl.SSLError) and e.args[0] == ssl.SSL_ERROR_EOF:
                        self.log.debug("ssl connection closed during handshake")
                    else:
                        self.log.debug("TLS handshake failed: %s", e)
                    return
                conn.is_ssl = True
                conn.sock.setblocking(False)

                if conn.sock.selected_alpn_protocol() == "h2":
                    conn.is_h2 = True
                    conn.handed_off = True
                    await async_handle_h2_connection(
                        conn.sock,
                        conn.client,
                        conn.server,
                        self.handler,
                        self.app.is_ssl,
                        self.tpool,
                    )
                    return

            while self.alive:
                # Read HTTP headers asynchronously on the event loop
                try:
                    header_data, body_start = await self._async_read_headers(conn.sock)
                except (TimeoutError, OSError):
                    break
                if not header_data:
                    break

                # Read the body asynchronously based on headers
                body_data = await self._async_read_body(
                    conn.sock, header_data, body_start
                )

                # Parse the buffered request (no I/O, just CPU).
                # Errors are handled here so we can send async responses.
                try:
                    parse_result = self._parse_buffered_request(
                        conn, header_data, body_start, body_data
                    )
                except _ParseError:
                    # _parse_buffered_request already sent the error response
                    break
                except Exception as e:
                    await self._async_handle_error(None, conn.sock, conn.client, e)
                    break

                if parse_result is None:
                    break

                req, http_request, resp, request_start = parse_result
                conn.req_count += 1

                keepalive = await self._dispatch(
                    req, conn, http_request, resp, request_start
                )

                if not keepalive or not self.alive:
                    break

                # Wait for the next request (keepalive)
                try:
                    await asyncio.wait_for(
                        self._wait_readable(conn.sock),
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

    def _do_tls_handshake(self, conn: TConn) -> ssl.SSLSocket:
        """Perform TLS handshake in blocking mode. Runs in the thread pool."""
        conn.sock.setblocking(True)
        conn.sock.settimeout(KEEPALIVE)
        assert conn.app.certfile is not None
        ssl_sock = sock.ssl_wrap_socket(conn.sock, conn.app.certfile, conn.app.keyfile)
        ssl_sock.settimeout(None)
        return ssl_sock

    async def _async_read_headers(self, s: socket.socket) -> tuple[bytes, bytes]:
        """Read from the socket until the header delimiter \\r\\n\\r\\n.

        Returns (header_data, body_start) where body_start contains any
        bytes read past the header boundary.  Returns (b"", b"") on EOF.
        """
        loop = asyncio.get_running_loop()
        buf = bytearray()
        while True:
            try:
                data = await asyncio.wait_for(
                    loop.sock_recv(s, 8192),
                    timeout=KEEPALIVE,
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
                self.log.warning("Request headers exceeded max size")
                return b"", b""

    async def _async_read_body(
        self,
        s: socket.socket,
        header_data: bytes,
        body_start: bytes,
    ) -> bytes:
        """Read the request body based on Content-Length or Transfer-Encoding.

        Returns the full body bytes. For requests with no body, returns b"".
        """
        from plain.runtime import settings

        max_body = settings.DATA_UPLOAD_MAX_MEMORY_SIZE or (10 * 1024 * 1024)

        # Parse Content-Length and Transfer-Encoding from raw header bytes
        content_length = -1
        is_chunked = False

        # Skip the request line, parse headers
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

        if content_length == 0 or (content_length < 0 and not is_chunked):
            return b""

        loop = asyncio.get_running_loop()
        body = bytearray(body_start)

        if content_length > 0:
            if content_length > max_body:
                # Let the parser handle the error — just return what we have
                return bytes(body)
            remaining = content_length - len(body)
            while remaining > 0:
                try:
                    chunk = await asyncio.wait_for(
                        loop.sock_recv(s, min(remaining, 65536)),
                        timeout=KEEPALIVE,
                    )
                except (TimeoutError, OSError):
                    break
                if not chunk:
                    break
                body.extend(chunk)
                remaining -= len(chunk)
            return bytes(body)

        if is_chunked:
            return await self._async_read_chunked_body(s, body, max_body)

        return bytes(body)

    async def _async_read_chunked_body(
        self,
        s: socket.socket,
        initial: bytearray,
        max_body: int,
    ) -> bytes:
        """Read a chunked transfer-encoded body asynchronously.

        We read the raw chunked data and return it as-is (including chunk
        framing). The parser's ChunkedReader will decode it properly.
        """
        loop = asyncio.get_running_loop()
        buf = initial

        while len(buf) <= max_body:
            try:
                chunk = await asyncio.wait_for(
                    loop.sock_recv(s, 65536),
                    timeout=KEEPALIVE,
                )
            except (TimeoutError, OSError):
                break
            if not chunk:
                break
            buf.extend(chunk)

            # Check for end of chunked encoding: 0\r\n\r\n
            if buf.endswith(b"0\r\n\r\n") or b"\r\n0\r\n\r\n" in buf:
                break

        return bytes(buf)

    async def _wait_readable(self, s: socket.socket) -> None:
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
        client: socket.socket,
        addr: Any,
        exc: BaseException,
    ) -> None:
        """Handle request errors, sending an appropriate HTTP error response."""
        request_start = datetime.now()
        addr = addr or ("", -1)  # unix socket case
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
            resp = Response(req, client)
            resp.status = f"{status_int} {reason}"
            resp.response_length = len(mesg)
            log_access(resp, req, request_time)

        try:
            await util.async_write_error(client, status_int, reason, mesg)
        except Exception:
            self.log.debug("Failed to send error message.")

    def is_parent_alive(self) -> bool:
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True

    def _parse_buffered_request(
        self,
        conn: TConn,
        header_data: bytes,
        body_start: bytes,
        body_data: bytes,
    ) -> tuple[Any, Any, Response, datetime] | None:
        """Parse a pre-buffered HTTP request. No socket I/O needed.

        Returns (req, http_request, resp, request_start) or None on EOF/close.
        Raises _ParseError for silently-handled connection issues.
        Lets HTTP protocol errors propagate so the caller can send
        async error responses.
        """
        try:
            # Create an unreader backed by the pre-read bytes
            unreader = BufferUnreader(header_data, body_data)

            # The parser reads from the unreader (all data is in memory)
            req = Request(self.app.is_ssl, unreader, conn.client, conn.req_count + 1)

            if not req:
                return None

            request_start = datetime.now()

            # Build the body stream from pre-read data.
            # The remaining_body_data() collects any leftover bytes the
            # header parser didn't consume plus the body bytes.
            remaining = unreader.remaining_body_data()
            body_io = io.BytesIO(remaining)

            http_request = create_request(req, conn.sock, conn.client, conn.server)
            http_request._stream = body_io
            http_request._read_started = False

            resp = Response(req, conn.sock, is_ssl=self.app.is_ssl)

            if not self.alive:
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
        if isinstance(exc, OSError):
            if exc.errno in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.debug("Client disconnected during dispatch: %s", exc)
            else:
                self.log.exception("Socket error during dispatch.")
            return False

        if resp.headers_sent:
            self.log.exception("Error handling request")
            try:
                conn.sock.shutdown(socket.SHUT_RDWR)
                conn.sock.close()
            except OSError:
                pass
        else:
            await self._async_handle_error(req, conn.sock, conn.client, exc)
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
            if hasattr(http_response, "aclose"):
                await http_response.aclose()

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
