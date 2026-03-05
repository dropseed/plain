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
import selectors
import signal
import socket
import ssl
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
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
from ..http.h2handler import handle_h2_connection
from ..http.response import Response, create_request
from .workertmp import WorkerHeartbeat

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..app import ServerApplication
    from ..http.message import Request

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


class PollableMethodQueue:
    """Pipe-based queue for deferring method calls to the main thread.

    Worker threads call defer() to queue a callback. The pipe write
    wakes the poller so the main loop processes queued calls without
    any locks — all poller and keepalive operations happen on one thread.
    """

    def __init__(self) -> None:
        self._read_fd, self._write_fd = os.pipe()
        # Non-blocking on both ends for BSD compatibility
        util.set_non_blocking(self._read_fd)
        util.set_non_blocking(self._write_fd)
        util.close_on_exec(self._read_fd)
        util.close_on_exec(self._write_fd)
        # deque.append/popleft are atomic under CPython's GIL
        self._queue: deque[tuple[Callable[..., Any], tuple[Any, ...]]] = deque()

    def fileno(self) -> int:
        return self._read_fd

    def defer(self, fn: Callable[..., Any], *args: Any) -> None:
        """Queue a function to run on the main thread."""
        self._queue.append((fn, args))
        try:
            os.write(self._write_fd, b"\x00")
        except OSError:
            pass  # Pipe full — main loop will still drain the queue

    def process(self, _fd: Any = None) -> None:
        """Drain the pipe and run all queued callbacks. Called on the main thread."""
        try:
            while os.read(self._read_fd, 4096):
                pass
        except OSError:
            pass

        while True:
            try:
                fn, args = self._queue.popleft()
            except IndexError:
                break
            fn(*args)

    def close(self) -> None:
        os.close(self._read_fd)
        os.close(self._write_fd)


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
        self._keep: deque[TConn] = deque()
        self.nr_conns: int = 0
        self._in_flight: int = 0
        self._accepting: bool = False

        # Async event loop for SSE channel connections
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._connection_manager: Any = None

    def __str__(self) -> str:
        return f"<Worker {self.pid}>"

    def notify(self) -> None:
        self.heartbeat.notify()

    def init_process(self) -> None:
        # Thread pool, poller, and method queue
        self.tpool: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=self.app.threads
        )
        self.poller: selectors.DefaultSelector = selectors.DefaultSelector()
        self._method_queue: PollableMethodQueue = PollableMethodQueue()

        # Reseed the random number generator
        util.seed()

        # For waking ourselves up (signals, reloader)
        self.PIPE: tuple[int, int] = os.pipe()
        for p in self.PIPE:
            util.set_non_blocking(p)
            util.close_on_exec(p)

        # Prevent listener sockets from leaking into subprocesses
        for s in self.sockets:
            util.close_on_exec(s.fileno())

        self.init_signals()

        # start the reloader
        if self.app.reload:

            def changed(fname: str) -> None:
                self.log.debug("Server worker reloading: %s modified", fname)
                self.alive = False
                os.write(self.PIPE[1], b"1")
                time.sleep(0.1)
                sys.exit(0)

            self.reloader = Reloader(callback=changed, watch_html=True)

        if self.reloader:
            self.reloader.start()

        # Start async event loop for SSE channels
        self._start_async_loop()

        # Enter main run loop
        self.booted = True
        self.run()

    def init_signals(self) -> None:
        # reset signaling
        for s in SIGNALS:
            signal.signal(s, signal.SIG_DFL)
        # init new signaling
        signal.signal(signal.SIGQUIT, self.handle_quit)
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_quit)
        signal.signal(signal.SIGWINCH, self.handle_winch)
        signal.signal(signal.SIGABRT, self.handle_abort)

        # Don't let SIGTERM disturb active requests
        # by interrupting system calls
        signal.siginterrupt(signal.SIGTERM, False)

        if hasattr(signal, "set_wakeup_fd"):
            signal.set_wakeup_fd(self.PIPE[1])

    def handle_exit(self, sig: int, frame: Any) -> None:
        self.alive = False

    def handle_quit(self, sig: int, frame: FrameType | None) -> None:
        self.alive = False
        self.tpool.shutdown(wait=False, cancel_futures=True)
        time.sleep(0.1)
        sys.exit(0)

    def handle_abort(self, sig: int, frame: FrameType | None) -> None:
        self.alive = False
        self.tpool.shutdown(wait=False, cancel_futures=True)
        sys.exit(1)

    def handle_winch(self, sig: int, fname: Any) -> None:
        # Ignore SIGWINCH in worker. Fixes a crash on OpenBSD.
        self.log.debug("worker: SIGWINCH ignored.")

    # ----- Async event loop for SSE channels -----

    def _start_async_loop(self) -> None:
        """Start a background async event loop for SSE channel connections."""
        try:
            from plain.channels.handler import AsyncConnectionManager
            from plain.channels.registry import channel_registry
        except ImportError:
            return  # channels module not available

        channel_registry.import_modules()

        self._async_loop = asyncio.new_event_loop()
        self._connection_manager = AsyncConnectionManager(self._async_loop)

        def run_loop(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        self._async_thread = threading.Thread(
            target=run_loop, args=(self._async_loop,), daemon=True
        )
        self._async_thread.start()

        # Start the connection manager (heartbeats + Postgres listener)
        self._async_loop.call_soon_threadsafe(self._connection_manager.start)

    def _stop_async_loop(self) -> None:
        """Stop the background async event loop."""
        if self._async_loop is None or self._connection_manager is None:
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._connection_manager.stop(), self._async_loop
            )
            future.result(timeout=3)
        except Exception:
            self._connection_manager.close_all()

        self._async_loop.call_soon_threadsafe(self._async_loop.stop)
        if self._async_thread:
            self._async_thread.join(timeout=2)

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

    def enqueue_req(self, conn: TConn) -> None:
        # conn.init() is called inside handle(), not here, so that SSL
        # handshake errors are caught in the worker thread instead of
        # crashing the main loop. (Ported from gunicorn PR #3440.)
        self._in_flight += 1
        try:
            self.tpool.submit(self._run_handle, conn)
        except RuntimeError:
            # Pool shut down (e.g. during SIGQUIT) — clean up counters
            self._in_flight -= 1
            self.nr_conns -= 1
            conn.close()

    def _run_handle(self, conn: TConn) -> None:
        """Run handle() in a worker thread, defer completion to main thread."""
        keepalive, conn = self.handle(conn)
        self._method_queue.defer(self.finish_request, keepalive, conn)

    def set_accept_enabled(self, enabled: bool) -> None:
        """Register or unregister listener sockets for accepting connections."""
        if enabled == self._accepting:
            return

        for listener in self.sockets:
            if enabled:
                listener.setblocking(False)
                server = listener.getsockname()
                self.poller.register(
                    listener,
                    selectors.EVENT_READ,
                    partial(self.accept, server),
                )
            else:
                self.poller.unregister(listener)

        self._accepting = enabled

    def accept(self, server: tuple[str, int], listener: socket.socket) -> None:
        try:
            sock, client = listener.accept()
            # initialize the connection object
            conn = TConn(self.app, sock, client, server)

            self.nr_conns += 1
            # wait until socket is readable
            self.poller.register(
                conn.sock,
                selectors.EVENT_READ,
                partial(self.on_client_socket_readable, conn),
            )
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.ECONNABORTED, errno.EWOULDBLOCK):
                raise

    def on_client_socket_readable(self, conn: TConn, client: socket.socket) -> None:
        # unregister the client from the poller
        self.poller.unregister(client)

        if conn.initialized:
            # remove the connection from keepalive
            try:
                self._keep.remove(conn)
            except ValueError:
                return

        # submit the connection to a worker
        self.enqueue_req(conn)

    def murder_keepalived(self) -> None:
        now = time.monotonic()
        while True:
            try:
                # remove the connection from the queue
                conn = self._keep.popleft()
            except IndexError:
                break

            # Connections in _keep always have timeout set via set_timeout()
            assert conn.timeout is not None, (
                "timeout should be set for keepalive connections"
            )
            delta = conn.timeout - now
            if delta > 0:
                # add the connection back to the queue
                self._keep.appendleft(conn)
                break
            else:
                self.nr_conns -= 1
                # remove the socket from the poller
                try:
                    self.poller.unregister(conn.sock)
                except OSError as e:
                    if e.errno != errno.EBADF:
                        raise
                except KeyError:
                    # already removed by the system, continue
                    pass
                except ValueError:
                    # already removed by the system continue
                    pass

                # close the socket
                conn.close()

    def is_parent_alive(self) -> bool:
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True

    def run(self) -> None:
        # Register the method queue so worker thread completions
        # wake up the poller
        self.poller.register(
            self._method_queue.fileno(),
            selectors.EVENT_READ,
            self._method_queue.process,
        )

        # Start accepting connections
        self.set_accept_enabled(True)

        while self.alive:
            # notify the arbiter we are alive
            self.notify()

            # Backpressure: stop accepting when at capacity
            self.set_accept_enabled(self.nr_conns < WORKER_CONNECTIONS)

            # Single unified event loop — handles accepts, client data,
            # and worker thread completions (via method queue pipe)
            events = self.poller.select(1.0)
            for key, _ in events:
                callback = key.data
                callback(key.fileobj)

            if not self.is_parent_alive():
                break

            # handle keepalive timeouts
            self.murder_keepalived()

        self.set_accept_enabled(False)
        self.tpool.shutdown(False)

        for s in self.sockets:
            s.close()

        # Graceful shutdown: keep processing completions until all
        # in-flight requests finish or the timeout expires
        from plain.runtime import settings

        deadline = time.monotonic() + settings.SERVER_GRACEFUL_TIMEOUT
        while self._in_flight > 0 and time.monotonic() < deadline:
            events = self.poller.select(0.5)
            for key, _ in events:
                callback = key.data
                callback(key.fileobj)

        # Stop the async event loop for SSE channels
        self._stop_async_loop()

        self.poller.close()
        self._method_queue.close()

    def finish_request(self, keepalive: bool, conn: TConn) -> None:
        """Process a completed request. Runs on the main thread via method queue."""
        self._in_flight -= 1

        if keepalive and self.alive:
            # flag the socket as non blocked
            conn.sock.setblocking(False)

            # register the connection
            conn.set_timeout()
            self._keep.append(conn)

            # add the socket to the event loop
            self.poller.register(
                conn.sock,
                selectors.EVENT_READ,
                partial(self.on_client_socket_readable, conn),
            )
        else:
            self.nr_conns -= 1
            conn.close()

    def handle(self, conn: TConn) -> tuple[bool, TConn]:
        keepalive = False
        req = None
        try:
            # Ensure blocking mode before init/parsing. Critical for keepalive
            # connections where finish_request sets non-blocking for the poller.
            conn.sock.setblocking(True)

            # For new connections, set a read timeout so slow clients can't
            # hold a thread indefinitely. Without this, a client that sends
            # partial headers ties up a thread pool slot until the server
            # timeout kills the whole worker. Keepalive connections are
            # protected by murder_keepalived() while idle on the poller.
            is_new = not conn.initialized
            if is_new:
                conn.sock.settimeout(KEEPALIVE)

            conn.init()

            # HTTP/2 connections are handled entirely within handle_h2_connection
            # which manages its own frame loop and stream dispatching.
            if conn.is_h2:
                conn.sock.settimeout(None)
                handle_h2_connection(
                    conn.sock,
                    conn.client,
                    conn.server,
                    self.handler,
                    self.app.is_ssl,
                )
                # H2 connection is done — don't keepalive
                return (False, conn)

            assert conn.parser is not None
            try:
                req = next(conn.parser)
            except TimeoutError:
                self.log.debug("Slow client timed out during request parsing")
                return (False, conn)

            if is_new:
                # Clear the read timeout now that parsing is done.
                conn.sock.settimeout(None)

            if not req:
                return (False, conn)

            # handle the request
            keepalive = self.handle_request(req, conn)
            if keepalive:
                return (keepalive, conn)
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
                self.handle_error(req, conn.sock, conn.client, e)

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
            self.handle_error(req, conn.sock, conn.client, e)

        return (False, conn)

    def _try_channel_handoff(self, req: Any, conn: TConn) -> bool:
        """Check if the request matches a channel and hand off the socket.

        Supports both SSE and WebSocket connections. The protocol is
        determined by the presence of WebSocket upgrade headers.

        Returns True if the connection was handed off (caller should NOT close it).
        Returns False if this is a normal request.
        """
        if self._connection_manager is None:
            return False

        from plain.channels.registry import channel_registry

        path = req.path or "/"
        channel = channel_registry.match(path)
        if channel is None:
            return False

        # Build a request for authorization
        http_request = create_request(req, conn.sock, conn.client, conn.server)

        if not channel.authorize(http_request):
            util.write_error(conn.sock, 403, "Forbidden", "Channel access denied")
            return True

        subscriptions = channel.subscribe(http_request)
        if not subscriptions:
            util.write_error(conn.sock, 400, "Bad Request", "No channel subscriptions")
            return True

        # Detect WebSocket upgrade
        from plain.channels.websocket import (
            build_accept_response,
            validate_handshake_headers,
        )

        is_ws, ws_key, ws_error = validate_handshake_headers(req.headers)

        if is_ws and ws_error:
            util.write_error(conn.sock, 400, "Bad Request", ws_error)
            return True

        # Dup the socket fd for the async thread to own
        sock_fd = os.dup(conn.sock.fileno())

        if is_ws:
            # Send the 101 Switching Protocols response before handoff
            conn.sock.sendall(build_accept_response(ws_key))

            self._async_loop.call_soon_threadsafe(
                self._connection_manager.accept_ws_connection,
                sock_fd,
                channel,
                subscriptions,
            )
        else:
            # SSE connection
            self._async_loop.call_soon_threadsafe(
                self._connection_manager.accept_sse_connection,
                sock_fd,
                channel,
                subscriptions,
            )

        return True

    def handle_request(self, req: Any, conn: TConn) -> bool:
        # Check for SSE channel handoff before normal request handling
        if self._try_channel_handoff(req, conn):
            return False  # No keepalive — socket ownership transferred

        resp: Response | None = None
        try:
            request_start = datetime.now()

            # Build Request directly from parsed HTTP message
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
            elif len(self._keep) >= self.max_keepalived:
                resp.force_close()

            signals.request_started.send(sender=self.__class__, request=http_request)
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
