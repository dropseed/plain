from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
# design:
# An asyncio event loop accepts connections and manages keepalive.
# Each connection is handled as an async task. HTTP parsing always
# runs in a thread pool. After parsing, URL resolution detects
# whether the view has async handlers:
#   Sync views:  full pipeline (middleware + view + write) in thread pool
#   Async views: middleware in thread pool, view awaited on event loop,
#                response written in thread pool
# Keepalive waits use asyncio.wait_for with a timeout.
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
from random import randint
from types import FrameType
from typing import TYPE_CHECKING, Any

from plain import signals
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
from ..http.response import Response, create_request
from .workertmp import WorkerHeartbeat

if TYPE_CHECKING:
    from ..app import ServerApplication
    from ..http.message import Request


class _H2Sentinel:
    """Sentinel value returned by _parse_request for HTTP/2 connections."""


_H2_SENTINEL = _H2Sentinel()

# Maximum jitter to add to max_requests to stagger worker restarts
MAX_REQUESTS_JITTER = 50

# Keep-alive connection timeout in seconds
KEEPALIVE = 2

# Maximum number of simultaneous client connections
WORKER_CONNECTIONS = 1000

SIGNALS = [
    signal.SIGABRT,
    signal.SIGHUP,
    signal.SIGQUIT,
    signal.SIGINT,
    signal.SIGTERM,
    signal.SIGWINCH,
]


def check_worker_config(threads: int, log: logging.Logger) -> None:
    max_keepalived = WORKER_CONNECTIONS - threads

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

        self.parser: http.RequestParser | None = None
        self.initialized: bool = False
        self.is_h2: bool = False
        self.handed_off: bool = False

        # set the socket to non blocking
        self.sock.setblocking(False)

    def init(self) -> None:
        if self.initialized:
            return

        if self.parser is None:
            # wrap the socket if needed
            if self.app.is_ssl:
                assert self.app.certfile is not None
                self.sock = sock.ssl_wrap_socket(
                    self.sock, self.app.certfile, self.app.keyfile
                )

                if self.sock.selected_alpn_protocol() == "h2":
                    self.is_h2 = True
                    self.initialized = True
                    return

            # initialize the parser
            self.parser = http.RequestParser(self.app.is_ssl, self.sock, self.client)

        self.initialized = True

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

        self.nr = 0

        if app.max_requests > 0:
            jitter = randint(0, MAX_REQUESTS_JITTER)
            self.max_requests = app.max_requests + jitter
        else:
            self.max_requests = sys.maxsize

        self.alive = True
        self.log = logging.getLogger("plain.server")
        self.heartbeat = heartbeat
        self.handler = handler

        self.max_keepalived: int = WORKER_CONNECTIONS - self.app.threads
        self.nr_conns: int = 0
        self._connection_tasks: set[asyncio.Task] = set()
        self._capacity_available: asyncio.Event = asyncio.Event()
        self._capacity_available.set()

    def __str__(self) -> str:
        return f"<Worker {self.pid}>"

    def notify(self) -> None:
        self.heartbeat.notify()

    def init_process(self) -> None:
        # Thread pool
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
            if self.nr_conns >= WORKER_CONNECTIONS:
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
            # Wait for the socket to become readable before dispatching
            # to the thread pool. Without this, slow/idle clients that
            # connect but don't send data would occupy thread pool slots
            # (up to the 2s parse timeout), starving real requests.
            try:
                await asyncio.wait_for(
                    self._wait_readable(conn.sock),
                    timeout=KEEPALIVE,
                )
            except TimeoutError:
                return

            while self.alive:
                # Parse HTTP in thread pool
                parse_result: (
                    tuple[Any, Any, Response, datetime] | _H2Sentinel | None
                ) = await loop.run_in_executor(self.tpool, self._parse_request, conn)

                if isinstance(parse_result, _H2Sentinel):
                    remaining = self.max_requests - self.nr
                    if self.max_requests < sys.maxsize and remaining <= 0:
                        self.log.info("Autorestarting worker after current request.")
                        self.alive = False
                        return
                    conn.handed_off = True
                    h2_streams = await async_handle_h2_connection(
                        conn.sock,
                        conn.client,
                        conn.server,
                        self.handler,
                        self.app.is_ssl,
                        self.tpool,
                        max_requests=remaining
                        if self.max_requests < sys.maxsize
                        else 0,
                    )
                    self.nr += h2_streams
                    if self.nr >= self.max_requests:
                        self.log.info("Autorestarting worker after current request.")
                        self.alive = False
                    return

                if parse_result is None:
                    break

                req, http_request, resp, request_start = parse_result

                # Detect async views (fast, safe on event loop).
                # FailHandler (from make_fail_handler) doesn't have this method.
                is_async = hasattr(
                    self.handler, "is_async_view"
                ) and self.handler.is_async_view(http_request)

                if is_async:
                    keepalive = await self._dispatch_async(
                        req, conn, http_request, resp, request_start
                    )
                else:
                    keepalive = await loop.run_in_executor(
                        self.tpool,
                        self._dispatch_sync,
                        req,
                        conn,
                        http_request,
                        resp,
                        request_start,
                    )

                if not keepalive or not self.alive:
                    break

                # Wait for the socket to become readable (next request)
                # or timeout (keepalive expiry)
                conn.sock.setblocking(False)
                try:
                    await asyncio.wait_for(
                        self._wait_readable(conn.sock),
                        timeout=KEEPALIVE,
                    )
                except TimeoutError:
                    # Keepalive timeout expired, close connection
                    break
        finally:
            self.nr_conns -= 1
            if self.nr_conns < WORKER_CONNECTIONS:
                self._capacity_available.set()
            if not conn.handed_off:
                conn.close()

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

    def handle_error(
        self, req: Request | None, client: socket.socket, addr: Any, exc: BaseException
    ) -> None:
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
            util.write_error(client, status_int, reason, mesg)
        except Exception:
            self.log.debug("Failed to send error message.")

    def is_parent_alive(self) -> bool:
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True

    def _parse_request(
        self, conn: TConn
    ) -> tuple[Any, Any, Response, datetime] | _H2Sentinel | None:
        """Parse HTTP and build request/response objects.

        Returns (req, http_request, resp, request_start) or None on failure.
        Returns _H2_SENTINEL if this is an HTTP/2 connection.
        All parse/connection errors are handled internally.
        """
        try:
            # Ensure blocking mode before init/parsing. Critical for keepalive
            # connections where _handle_connection sets non-blocking for readability waiting.
            conn.sock.setblocking(True)

            # For new connections, set a read timeout so slow clients can't
            # hold a thread indefinitely. Without this, a client that sends
            # partial headers ties up a thread pool slot until the server
            # timeout kills the whole worker. Keepalive connections are
            # protected by asyncio.wait_for timeout while idle.
            is_new = not conn.initialized
            if is_new:
                conn.sock.settimeout(KEEPALIVE)

            conn.init()

            if conn.is_h2:
                conn.sock.settimeout(None)
                return _H2_SENTINEL

            assert conn.parser is not None
            try:
                req = next(conn.parser)
            except TimeoutError:
                self.log.debug("Slow client timed out during request parsing")
                return None

            if is_new:
                # Clear the read timeout now that parsing is done.
                conn.sock.settimeout(None)

            if not req:
                return None

            request_start = datetime.now()
            http_request = create_request(req, conn.sock, conn.client, conn.server)

            resp = Response(req, conn.sock, is_ssl=self.app.is_ssl)
            self.nr += 1
            if self.nr >= self.max_requests:
                if self.alive:
                    self.log.info("Autorestarting worker after current request.")
                    self.alive = False
                resp.force_close()

            if not self.alive:
                resp.force_close()
            elif self.nr_conns >= self.max_keepalived:
                resp.force_close()

            return (req, http_request, resp, request_start)
        except http.errors.NoMoreData as e:
            self.log.debug("Ignored premature client disconnection. %s", e)
        except StopIteration as e:
            self.log.debug("Closing connection. %s", e)
        except ssl.SSLError as e:
            if e.args[0] == ssl.SSL_ERROR_EOF:
                self.log.debug("ssl connection closed")
                conn.sock.close()
            else:
                self.log.debug("Error processing SSL request.")
                self.handle_error(None, conn.sock, conn.client, e)
        except OSError as e:
            if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.exception("Socket error processing request.")
            else:
                if e.errno == errno.ECONNRESET:
                    self.log.debug("Ignoring connection reset")
                elif e.errno == errno.ENOTCONN:
                    self.log.debug("Ignoring socket not connected")
                else:
                    self.log.debug("Ignoring connection epipe")
        except Exception as e:
            self.handle_error(None, conn.sock, conn.client, e)

        return None

    def _finish_request(
        self,
        req: Any,
        resp: Response,
        http_response: Any,
        request_start: datetime,
    ) -> bool:
        """Write response, log access, and determine keepalive."""
        try:
            resp.write_response(http_response)
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

    def _handle_dispatch_error(
        self, req: Any, resp: Response, conn: TConn, exc: BaseException
    ) -> bool:
        """Handle exceptions from dispatch methods. Returns False (no keepalive)."""
        if isinstance(exc, OSError):
            # Gracefully handle common client disconnects
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
            # Send a proper HTTP 500 to the client
            self.handle_error(req, conn.sock, conn.client, exc)
        return False

    def _dispatch_sync(
        self,
        req: Any,
        conn: TConn,
        http_request: Any,
        resp: Response,
        request_start: datetime,
    ) -> bool:
        """Sync dispatch: signal + full middleware pipeline + write response."""
        try:
            signals.request_started.send(sender=self.__class__, request=http_request)
            http_response = self.handler.get_response(http_request)
            return self._finish_request(req, resp, http_response, request_start)
        except Exception as exc:
            return self._handle_dispatch_error(req, resp, conn, exc)

    async def _dispatch_async(
        self,
        req: Any,
        conn: TConn,
        http_request: Any,
        resp: Response,
        request_start: datetime,
    ) -> bool:
        """Async dispatch: middleware in thread pool, async view on event loop."""
        loop = asyncio.get_running_loop()
        try:
            # Send signal in thread pool (handlers may do sync work)
            await loop.run_in_executor(
                self.tpool,
                lambda: signals.request_started.send(
                    sender=self.__class__, request=http_request
                ),
            )
            # Async middleware pipeline + view
            http_response = await self.handler.get_response_async(
                http_request, self.tpool
            )

            # Check for async streaming response (SSE, etc.)
            from plain.http import AsyncStreamingResponse

            if isinstance(http_response, AsyncStreamingResponse):
                return await self._stream_async_response(
                    req, resp, http_response, request_start
                )

            # Write response in thread pool (blocking socket I/O)
            return await loop.run_in_executor(
                self.tpool,
                self._finish_request,
                req,
                resp,
                http_response,
                request_start,
            )
        except Exception as exc:
            # Run error handler in thread pool — it does blocking socket I/O
            return await loop.run_in_executor(
                self.tpool, self._handle_dispatch_error, req, resp, conn, exc
            )

    async def _stream_async_response(
        self,
        req: Any,
        resp: Response,
        http_response: Any,
        request_start: datetime,
    ) -> bool:
        """Stream an async response (SSE, etc.) chunk by chunk.

        Headers are sent immediately, then each chunk from the async iterator
        is written as it arrives. This keeps the event loop free between chunks.
        """
        loop = asyncio.get_running_loop()

        # Stream chunks: iterate on event loop, write in thread pool.
        # Client disconnect (OSError) during write is normal for SSE.
        client_disconnected = False
        try:
            # Prepare and send headers in thread pool
            await loop.run_in_executor(
                self.tpool,
                lambda: (resp.prepare_response(http_response), resp.send_headers()),
            )

            async for chunk in http_response:
                try:
                    await loop.run_in_executor(self.tpool, resp.write, chunk)
                except OSError:
                    client_disconnected = True
                    break
        finally:
            # Close the async iterator (e.g. async generator cleanup)
            if hasattr(http_response, "aclose"):
                await http_response.aclose()

            # Finalize: close chunked encoding, log access, clean up
            def _finalize() -> None:
                try:
                    if not client_disconnected:
                        resp.close()
                except OSError:
                    pass
                finally:
                    request_time = datetime.now() - request_start
                    if http_response.log_access:
                        log_access(resp, req, request_time)
                    if hasattr(http_response, "close"):
                        http_response.close()

            await loop.run_in_executor(self.tpool, _finalize)

        if client_disconnected or resp.should_close():
            return False
        return True
