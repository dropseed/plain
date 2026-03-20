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
#     1. Accept + TLS via asyncio.start_server(ssl=...) → reader/writer
#     2. Read header bytes (async, until \r\n\r\n)
#     3. Parse headers from buffer (inline, no I/O)
#     4. Read body bytes (async, based on Content-Length or chunked)
#     5. Dispatch view (thread pool for sync, event loop for async)
#     6. Write response (async)
#   Keepalive waits use asyncio.wait_for with a timeout.
import asyncio
import logging
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import FrameType
from typing import TYPE_CHECKING, Any

from plain.internal.reloader import Reloader

from .. import sock, util
from ..connection import Connection
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
        healthcheck_path = settings.HEALTHCHECK_PATH
        self.healthcheck_path_bytes: bytes = (
            healthcheck_path.encode("ascii") if healthcheck_path else b""
        )
        self.nr_conns: int = 0
        self._connection_tasks: set[asyncio.Task] = set()
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
        loop.add_signal_handler(signal.SIGUSR1, self._handle_memory_signal)
        # SIGABRT/SIGWINCH use signal.signal() because they need the
        # (sig, frame) signature and call sys.exit() directly
        signal.signal(signal.SIGABRT, self.handle_abort)
        signal.signal(signal.SIGWINCH, self.handle_winch)
        signal.siginterrupt(signal.SIGTERM, False)

        # Build SSL context once for all listeners
        ssl_ctx = None
        if self.app.is_ssl:
            assert self.app.certfile is not None
            ssl_ctx = sock.ssl_context(self.app.certfile, self.app.keyfile)

        # Capacity semaphore for backpressure
        self._capacity_semaphore: asyncio.Semaphore = asyncio.Semaphore(
            self.max_connections
        )

        # Start servers (one per listener socket)
        servers: list[asyncio.Server] = []
        for listener in self.sockets:
            assert listener.sock is not None, "Listener socket is closed"
            listener.sock.setblocking(False)
            server = await asyncio.start_server(
                self._on_connection,
                sock=listener.sock,
                ssl=ssl_ctx,
                ssl_handshake_timeout=10 if ssl_ctx else None,
            )
            servers.append(server)

        # Heartbeat loop
        while self.alive:
            self.notify()
            if not self.is_parent_alive():
                break

            # Check executor health: submit a no-op and see if it completes
            # within the timeout window. If not, the thread pool is stalled
            # and we stop heartbeating so the arbiter will kill/restart us.
            # (self.timeout is SERVER_TIMEOUT/2; the arbiter kills after
            # SERVER_TIMEOUT, so this can't cause a false kill.)
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(self.tpool, lambda: None),
                    timeout=self.timeout,
                )
            except TimeoutError:
                self.log.warning(
                    "Thread pool stalled (no-op didn't complete in %ss), "
                    "stopping heartbeat to trigger restart",
                    self.timeout,
                )
                break

            # Surface server crashes
            for server in servers:
                if not server.is_serving():
                    self.log.error("Server stopped serving unexpectedly")
                    self.alive = False
                    break
            await asyncio.sleep(1.0)

        # Stop accepting new connections (don't await wait_closed() —
        # it blocks until all connection tasks finish, bypassing
        # _graceful_shutdown's timeout enforcement)
        for server in servers:
            server.close()

        await self._graceful_shutdown()

    async def _on_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Callback for each new connection from asyncio.start_server."""
        # Reject immediately if at capacity — the connection is already
        # accepted (and TLS-negotiated for SSL) by the time we get here,
        # so queuing behind a semaphore would just waste resources.
        if self._capacity_semaphore.locked():
            self.log.debug("Connection rejected: at capacity")
            writer.close()
            await writer.wait_closed()
            return
        await self._capacity_semaphore.acquire()

        client = writer.get_extra_info("peername")
        server_addr = writer.get_extra_info("sockname")
        is_ssl = writer.get_extra_info("ssl_object") is not None

        conn = Connection(self.app, reader, writer, client, server_addr, is_ssl=is_ssl)
        self.nr_conns += 1

        task = asyncio.current_task()
        assert task is not None
        self._connection_tasks.add(task)
        task.add_done_callback(self._connection_tasks.discard)

        try:
            await self._handle_connection(conn)
        except ConnectionError:
            pass
        finally:
            self._capacity_semaphore.release()
            self.nr_conns -= 1
            conn.close()

    async def _handle_connection(self, conn: Connection) -> None:
        if conn.is_ssl:
            ssl_object = conn.writer.get_extra_info("ssl_object")
            alpn = ssl_object.selected_alpn_protocol() if ssl_object else None

            if alpn == "h2":
                conn.is_h2 = True
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

    async def _graceful_shutdown(self) -> None:
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

    def _handle_memory_signal(self) -> None:
        from ._memory import signal_handler

        signal_handler()

    def handle_winch(self, sig: int, fname: Any) -> None:
        # Ignore SIGWINCH in worker. Fixes a crash on OpenBSD.
        self.log.debug("worker: SIGWINCH ignored.")

    def is_parent_alive(self) -> bool:
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True
