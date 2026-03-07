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
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import FrameType
from typing import TYPE_CHECKING, Any

from plain.internal.reloader import Reloader

from .. import sock, util
from ..connection import KEEPALIVE, Connection
from ..http import h1
from ..http.h2 import async_handle_h2_connection
from .workertmp import WorkerHeartbeat

if TYPE_CHECKING:
    from ..app import ServerApplication

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

        # Enable asyncio debug mode in development to detect blocking calls
        # in async views. Logs a warning when a callback takes > 0.1s.
        from plain.runtime import settings

        if settings.DEBUG:
            loop.set_debug(True)
            loop.slow_callback_duration = 0.1

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

            conn = Connection(self.app, client_sock, client_addr, server)
            self.nr_conns += 1

            task = loop.create_task(self._handle_connection(conn))
            self._connection_tasks.add(task)
            task.add_done_callback(self._connection_tasks.discard)

    async def _handle_connection(self, conn: Connection) -> None:
        try:
            # Wait for the socket to become readable before doing anything.
            # This prevents slow/idle clients from consuming resources.
            try:
                await asyncio.wait_for(
                    conn.wait_readable(),
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

            # HTTP/1.1
            await h1.handle_connection(self, conn)
        finally:
            self.nr_conns -= 1
            if self.nr_conns < self.max_connections:
                self._capacity_available.set()
            if not conn.handed_off:
                conn.close()

    async def _async_tls_handshake(
        self, conn: Connection
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

    def is_parent_alive(self) -> bool:
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True
