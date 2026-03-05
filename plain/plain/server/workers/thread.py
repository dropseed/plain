from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
# design:
# A threaded worker accepts connections in the main loop, accepted
# connections are added to the thread pool as a connection job.
# Keepalive connections are put back in the loop waiting for an event.
# If no event happen after the keep alive timeout, the connection is
# closed.
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
from plain.http import AsyncStreamingResponse
from plain.internal.reloader import Reloader
from plain.views.websocket import WebSocketUpgradeResponse

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

_H2_SENTINEL = object()

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

        self.timeout: float | None = None
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

                # Check ALPN-negotiated protocol
                if (
                    hasattr(self.sock, "selected_alpn_protocol")
                    and self.sock.selected_alpn_protocol() == "h2"
                ):
                    self.is_h2 = True
                    self.initialized = True
                    return

            # initialize the parser (HTTP/1.x)
            self.parser = http.RequestParser(self.app.is_ssl, self.sock, self.client)

        self.initialized = True

    def set_timeout(self) -> None:
        # set the timeout
        self.timeout = time.monotonic() + KEEPALIVE

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

        # Reset all signals to default before setting up asyncio handlers
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

    def handle_exit_async(self) -> None:
        self.alive = False

    def handle_quit_async(self) -> None:
        self.alive = False
        self.tpool.shutdown(wait=False, cancel_futures=True)

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

    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        # Add signal handlers
        loop.add_signal_handler(signal.SIGTERM, self.handle_exit_async)
        loop.add_signal_handler(signal.SIGINT, self.handle_quit_async)
        loop.add_signal_handler(signal.SIGQUIT, self.handle_quit_async)
        signal.signal(signal.SIGABRT, self.handle_abort)
        signal.signal(signal.SIGWINCH, self.handle_winch)

        # Don't let SIGTERM disturb active requests
        # by interrupting system calls
        signal.siginterrupt(signal.SIGTERM, False)

        # Start accepting on all listener sockets
        for listener in self.sockets:
            listener.setblocking(False)
            loop.create_task(self._accept_loop(loop, listener))

        # Main heartbeat loop
        while self.alive:
            self.notify()

            if not self.is_parent_alive():
                break

            await asyncio.sleep(1.0)

        # Graceful shutdown
        await self._graceful_shutdown(loop)

    async def _accept_loop(
        self, loop: asyncio.AbstractEventLoop, listener: sock.BaseSocket
    ) -> None:
        server: tuple[str, int] = listener.getsockname()  # type: ignore[assignment]
        while self.alive:
            if self.nr_conns >= WORKER_CONNECTIONS:
                await asyncio.sleep(0.1)  # backpressure
                continue
            try:
                client_sock, client = await loop.sock_accept(listener)  # type: ignore[arg-type]
                self.nr_conns += 1
                loop.create_task(
                    self._handle_connection(loop, client_sock, client, server)
                )
            except OSError as e:
                if e.errno not in (
                    errno.EAGAIN,
                    errno.ECONNABORTED,
                    errno.EWOULDBLOCK,
                ):
                    raise

    async def _wait_readable(
        self, loop: asyncio.AbstractEventLoop, s: socket.socket
    ) -> None:
        """Wait until a socket has data to read."""
        fut = loop.create_future()

        def _ready() -> None:
            if not fut.done():
                fut.set_result(None)

        loop.add_reader(s.fileno(), _ready)
        try:
            await fut
        finally:
            loop.remove_reader(s.fileno())

    async def _handle_connection(
        self,
        loop: asyncio.AbstractEventLoop,
        client_sock: socket.socket,
        client: tuple[str, int],
        server: tuple[str, int],
    ) -> None:
        conn = TConn(self.app, client_sock, client, server)
        try:
            # Parse and handle the first request
            keepalive = await self._dispatch_request(loop, conn)

            while keepalive and self.alive:
                # Wait for socket to be readable (keepalive)
                conn.sock.setblocking(False)
                try:
                    await asyncio.wait_for(
                        self._wait_readable(loop, conn.sock),
                        timeout=KEEPALIVE,
                    )
                except TimeoutError:
                    break  # keepalive timeout

                # Socket is readable -- handle next request
                keepalive = await self._dispatch_request(loop, conn)
        except Exception:
            self.log.debug("Connection error", exc_info=True)
        finally:
            self.nr_conns -= 1
            if not conn.handed_off:
                conn.close()

    async def _dispatch_request(
        self, loop: asyncio.AbstractEventLoop, conn: TConn
    ) -> bool:
        """Parse a request in the executor, then dispatch sync or async."""
        # Parse the request in executor (blocking I/O)
        parse_result = await loop.run_in_executor(self.tpool, self._parse_request, conn)
        if parse_result is None:
            return False

        # HTTP/2 sentinel: hand off to async H2 handler
        if parse_result is _H2_SENTINEL:
            conn.handed_off = True
            await self._handle_h2(loop, conn)
            return False

        req, http_request = parse_result

        # Resolve the URL to check if the view is async
        from plain.urls import get_resolver

        try:
            resolver_match = get_resolver().resolve(http_request.path_info)
        except Exception:
            # Fall back to sync handling if resolution fails
            # (middleware will handle the 404)
            return await loop.run_in_executor(
                self.tpool, self.handle_request, req, conn, http_request
            )

        # Attach resolver_match so the handler can skip re-resolving
        http_request.resolver_match = resolver_match

        view_func = resolver_match.view
        is_async_view = getattr(view_func, "view_is_async", False)

        if is_async_view:
            return await self._handle_async_request(loop, req, conn, http_request)
        else:
            return await loop.run_in_executor(
                self.tpool, self.handle_request, req, conn, http_request
            )

    async def _handle_h2(self, loop: asyncio.AbstractEventLoop, conn: TConn) -> None:
        """Run the async H2 handler on the connection socket."""
        await async_handle_h2_connection(
            conn.sock,
            conn.client,
            conn.server,
            self.handler,
            self.app.is_ssl,
            self.tpool,
        )

    async def _graceful_shutdown(self, loop: asyncio.AbstractEventLoop) -> None:
        # Stop accepting new connections
        for s in self.sockets:
            s.close()

        # Wait for in-flight connections to finish
        from plain.runtime import settings

        deadline = time.monotonic() + settings.SERVER_GRACEFUL_TIMEOUT
        while self.nr_conns > 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.5)

        self.tpool.shutdown(False)

    def _parse_request(self, conn: TConn) -> Any:
        """Parse an HTTP request from the connection. Runs in executor.

        Returns (raw_req, http_request), _H2_SENTINEL, or None.
        """
        try:
            # Ensure blocking mode before init/parsing
            conn.sock.setblocking(True)

            is_new = not conn.initialized
            if is_new:
                conn.sock.settimeout(KEEPALIVE)

            conn.init()

            # HTTP/2: return sentinel so _dispatch_request hands off to async
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
                conn.sock.settimeout(None)

            if not req:
                return None

            http_request = create_request(req, conn.sock, conn.client, conn.server)
            return (req, http_request)

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

    def _prepare_request(self, req: Any, conn: TConn, http_request: Any) -> Response:
        """Common request setup: create Response, check limits, send signal."""
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

        signals.request_started.send(sender=self.__class__, request=http_request)
        return resp

    async def _handle_async_request(
        self,
        loop: asyncio.AbstractEventLoop,
        req: Any,
        conn: TConn,
        http_request: Any,
    ) -> bool:
        """Handle a request with an async view on the event loop."""
        resp: Response | None = None
        try:
            request_start = datetime.now()
            resp = self._prepare_request(req, conn, http_request)

            # Use the async handler path (with middleware, in executor)
            http_response = await self.handler.aget_response(
                http_request, executor=self.tpool
            )

            # Check if this is a WebSocket upgrade
            if isinstance(http_response, WebSocketUpgradeResponse):
                await self._handle_websocket(
                    loop, req, conn, http_request, http_response
                )
                return False

            try:
                # Check if this is an async streaming response
                if isinstance(http_response, AsyncStreamingResponse):
                    await self._write_async_response(resp, http_response)
                else:
                    # Write sync response (headers + body)
                    await loop.run_in_executor(
                        self.tpool, resp.write_response, http_response
                    )
            finally:
                request_time = datetime.now() - request_start
                if http_response.log_access:
                    log_access(resp, req, request_time)
                if hasattr(http_response, "close"):
                    http_response.close()

            if resp.should_close():
                self.log.debug("Closing connection.")
                return False
        except OSError:
            raise
        except Exception:
            if resp and resp.headers_sent:
                self.log.exception("Error handling request")
                try:
                    conn.sock.shutdown(socket.SHUT_RDWR)
                    conn.sock.close()
                except OSError:
                    pass
                return False
            raise

        return True

    async def _handle_websocket(
        self,
        loop: asyncio.AbstractEventLoop,
        req: Any,
        conn: TConn,
        http_request: Any,
        http_response: Any,
    ) -> None:
        """Handle a WebSocket upgrade and lifecycle."""
        from plain.server.protocols.websocket import (
            build_accept_response,
            handle_websocket_connection,
            validate_handshake_headers,
        )

        ws_view = http_response.ws_view

        # Validate WebSocket handshake headers
        is_ws, ws_key, ws_error = validate_handshake_headers(req.headers)
        if not is_ws or ws_error:
            util.write_error(
                conn.sock,
                400,
                "Bad Request",
                ws_error or "Not a WebSocket request",
            )
            return

        # Mark as handed off now that handshake is validated
        conn.handed_off = True

        # Send the 101 Switching Protocols response
        conn.sock.sendall(build_accept_response(ws_key))

        # Set up async reader/writer
        conn.sock.setblocking(False)
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.create_connection(lambda: protocol, sock=conn.sock)
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)

        ws_view.bind_transport(reader, writer)

        await handle_websocket_connection(reader, writer, ws_view, self.log)

    async def _write_async_response(self, resp: Response, http_response: Any) -> None:
        """Write an AsyncStreamingResponse to the socket."""
        loop = asyncio.get_running_loop()
        status = f"{http_response.status_code} {http_response.reason_phrase}"
        resp.set_status_and_headers(status, http_response.header_items())
        await loop.run_in_executor(self.tpool, resp.send_headers)

        # Iterate async streaming content, write chunks in executor
        # to avoid blocking the event loop on slow clients
        async for chunk in http_response:
            await loop.run_in_executor(self.tpool, resp.write, chunk)

        await loop.run_in_executor(self.tpool, resp.close)

    def handle_request(self, req: Any, conn: TConn, http_request: Any = None) -> bool:
        resp: Response | None = None
        try:
            request_start = datetime.now()

            # Build Request directly from parsed HTTP message (if not already built)
            if http_request is None:
                http_request = create_request(req, conn.sock, conn.client, conn.server)

            resp = self._prepare_request(req, conn, http_request)
            http_response = self.handler.get_response(http_request)

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
        except OSError:
            # pass to next try-except level
            raise
        except Exception:
            if resp and resp.headers_sent:
                # If the requests have already been sent, we should close the
                # connection to indicate the error.
                self.log.exception("Error handling request")
                try:
                    conn.sock.shutdown(socket.SHUT_RDWR)
                    conn.sock.close()
                except OSError:
                    pass
                raise StopIteration()
            raise

        return True
