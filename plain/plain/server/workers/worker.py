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
#   Keepalive waits race the next request against worker shutdown
#   (see h1.handle_connection).
import asyncio
import logging
import os
import random
import signal
import ssl
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from types import FrameType
from typing import TYPE_CHECKING, Any

from plain.exceptions import ImproperlyConfigured
from plain.internal.reloader import Reloader
from plain.logs import get_framework_logger

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

# Slice of SERVER_GRACEFUL_TIMEOUT reserved for cancelling leftover
# connection tasks and tearing down after the drain wait, so a
# SIGTERM-initiated shutdown finishes before the arbiter's SIGKILL lands.
DRAIN_TEARDOWN_MARGIN = 2.0

# Ceiling on how long a connection may spend reading its final request
# once shutdown starts (see drain_read_deadline). Without a bound, a
# client trickling bytes (each recv resets the per-recv timeout) could
# pin its connection task for the whole graceful window.
DRAIN_READ_TIMEOUT = 5.0


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
        sockets: Sequence[sock.BaseSocket],
        app: ServerApplication,
        timeout: float,
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
        self.log = get_framework_logger()
        self.heartbeat = heartbeat
        self.handler = handler

        from plain.runtime import settings

        self.max_connections: int = settings.SERVER_CONNECTIONS
        self.max_keepalived: int = self.max_connections - self.app.threads
        self.max_body: int = settings.DATA_UPLOAD_MAX_MEMORY_SIZE or (10 * 1024 * 1024)
        self.keepalive_timeout: float = settings.SERVER_KEEPALIVE_TIMEOUT
        if self.keepalive_timeout <= 0:
            # Belt to the preflight check's braces — env vars bypass
            # settings.py review, and a non-positive value would close
            # every connection before it serves a single request.
            raise ImproperlyConfigured(
                f"SERVER_KEEPALIVE_TIMEOUT must be positive "
                f"(got {self.keepalive_timeout})."
            )
        healthcheck_path = settings.HEALTHCHECK_PATH
        self.healthcheck_path_bytes: bytes = (
            healthcheck_path.encode("ascii") if healthcheck_path else b""
        )
        self.nr_conns: int = 0
        # Event loop for run(), published so the Reloader thread can hand
        # _begin_drain to it. None until run() starts.
        self._loop: asyncio.AbstractEventLoop | None = None
        # Throttle so hitting the connection cap logs a warning at most
        # once a minute, not once per rejected connection (rejections
        # arrive at connection rate exactly when the worker is
        # saturated).
        self._capacity_warned_at: float = float("-inf")
        # Absolute time.monotonic() deadline for post-shutdown reads,
        # published when shutdown starts (None while alive). Connection
        # loops read it live via h1._recv_timeout, so it also bounds
        # requests that were already mid-read when the signal landed.
        self.drain_read_deadline: float | None = None
        self._connection_tasks: set[asyncio.Task] = set()
        self._servers: list[asyncio.Server] = []
        self._notify_during_drain = True
        # Set (on the event loop) when shutdown starts — H2 connections
        # watch this to refuse new streams and drain; h1 keepalive waits
        # watch it to collapse their idle window (h1 responses gate on
        # alive).
        self.shutdown_event: asyncio.Event = asyncio.Event()
        # Worker-level H2 stream budget — limits total in-flight H2 streams
        # across all connections to avoid overwhelming the thread pool.
        self._h2_stream_budget: asyncio.Semaphore = asyncio.Semaphore(
            self.app.threads * 4
        )

        # Worker recycling — gracefully restart after N requests to prevent
        # memory accumulation from fragmentation, C extension leaks, etc.
        # Disabled in reload mode since file-change restarts already recycle workers,
        # and retirement during reload causes unnecessary extra restart cycles.
        # Jitter is applied later in init_process() after util.seed() so
        # each forked worker gets a unique value.
        self.max_requests: int = 0 if self.app.reload else settings.SERVER_MAX_REQUESTS
        self.total_requests: int = 0

    def __str__(self) -> str:
        return f"<Worker {self.pid}>"

    def _count_request(self) -> None:
        """Increment the request counter and signal for replacement if the limit is reached."""
        self.total_requests += 1
        if (
            self.max_requests
            and self.total_requests >= self.max_requests
            and not self.heartbeat.is_retiring()
        ):
            self.heartbeat.set_retiring()
            self.log.info(
                "Worker reached max requests, requesting replacement",
                extra={"max_requests": self.max_requests},
            )

    def notify(self) -> None:
        self.heartbeat.notify()

    def init_process(self) -> None:
        # Thread pool — used only for application code (middleware + views)
        self.tpool: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=self.app.threads
        )

        # Reseed the random number generator (must happen before jitter)
        util.seed()

        # Apply jitter after reseeding so each forked worker gets unique jitter
        from plain.runtime import settings

        if self.max_requests and settings.SERVER_MAX_REQUESTS_JITTER:
            self.max_requests += random.randint(
                -settings.SERVER_MAX_REQUESTS_JITTER,
                settings.SERVER_MAX_REQUESTS_JITTER,
            )
            self.max_requests = max(1, self.max_requests)
            self.log.debug(
                "Worker max_requests set with jitter",
                extra={"max_requests": self.max_requests},
            )

        # Prevent listener sockets from leaking into subprocesses
        for s in self.sockets:
            util.close_on_exec(s.fileno())

        # Reset all signals to default before asyncio takes over
        for s in SIGNALS:
            signal.signal(s, signal.SIG_DFL)

        # start the reloader
        if self.app.reload:

            def changed(fname: str) -> None:
                self.log.debug("Server worker reloading", extra={"modified": fname})
                # Runs on the Reloader thread — hand the drain to the
                # event loop so shutdown_event is set alongside alive and
                # idle connections collapse their waits immediately.
                # Falls back to the alive flag if the loop isn't up yet
                # or is already closed (post-drain save storm) — an
                # unguarded RuntimeError here would kill the watcher
                # thread. (sys.exit() here would only end the watcher
                # thread, not the process.)
                try:
                    if self._loop is None:
                        raise RuntimeError("Event loop not running")
                    self._loop.call_soon_threadsafe(self._begin_drain)
                except RuntimeError:
                    self.alive = False

            self.reloader = Reloader(callback=changed, watch_html=True)

        if self.reloader:
            self.reloader.start()

        # Enter main run loop
        self.booted = True
        try:
            asyncio.run(self.run())
        finally:
            # The loop is closed — stop the reloader callback from
            # scheduling onto it.
            self._loop = None

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self._loop = loop

        # Enable asyncio debug mode in development to detect blocking calls
        # in async views. Logs a warning when a callback takes > 0.1s.
        from plain.runtime import settings

        if settings.DEBUG:
            loop.set_debug(True)
            loop.slow_callback_duration = 0.1

        # Port scans and TCP health checks (load balancers, `nc -z`) abort
        # mid-TLS-handshake constantly — asyncio logs each one as an error
        # with a traceback. Routine connection noise, not application errors.
        def _accept_error_handler(
            loop: asyncio.AbstractEventLoop, context: dict[str, Any]
        ) -> None:
            if context.get(
                "message"
            ) == "Error on transport creation for incoming connection" and isinstance(
                context.get("exception"),
                ConnectionResetError
                | ConnectionAbortedError  # handshake timeout on 3.13+
                | BrokenPipeError
                | ssl.SSLError
                | TimeoutError,
            ):
                self.log.debug(
                    "Connection aborted during accept/TLS handshake",
                    extra={"error": repr(context.get("exception"))},
                )
                return
            loop.default_exception_handler(context)

        loop.set_exception_handler(_accept_error_handler)

        # Signal handlers
        loop.add_signal_handler(signal.SIGTERM, self._signal_exit)
        loop.add_signal_handler(signal.SIGINT, self._signal_quit)
        loop.add_signal_handler(signal.SIGQUIT, self._signal_quit)
        loop.add_signal_handler(signal.SIGUSR1, self._handle_memory_signal)
        # SIGABRT/SIGWINCH use signal.signal() because they take the
        # (sig, frame) signature; handle_abort also exits the process
        # directly (handle_winch just ignores the signal)
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
        for listener in self.sockets:
            assert listener.sock is not None, "Listener socket is closed"
            listener.sock.setblocking(False)
            server = await asyncio.start_server(
                self._on_connection,
                sock=listener.sock,
                ssl=ssl_ctx,
                ssl_handshake_timeout=10 if ssl_ctx else None,
            )
            self._servers.append(server)

        # Heartbeat loop. _signal_exit can close self._servers between any
        # two awaits in this body (see its comment) — per-tick checks on
        # server state would false-positive during shutdown.
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
                    "Thread pool stalled, stopping heartbeat to trigger restart",
                    extra={"timeout": self.timeout},
                )
                self._notify_during_drain = False
                break

            await asyncio.sleep(1.0)

        # Any loop exit means shutdown — the break paths (parent death,
        # stalled thread pool) leave alive True, but connection handling
        # gates on this state: h1 stops taking keep-alive requests once
        # alive is False (requests parsed from here on respond with
        # Connection: close; responses already dispatched still go out
        # keep-alive), and h2 connections watch shutdown_event to refuse
        # new streams and drain.
        self._begin_drain()

        # Stop accepting new connections (don't await wait_closed() —
        # it blocks until all connection tasks finish, bypassing
        # _graceful_shutdown's timeout enforcement)
        for server in self._servers:
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
            # Idle keep-alive connections hold slots for
            # SERVER_KEEPALIVE_TIMEOUT, so hitting the cap should be
            # diagnosable from logs rather than a mystery bare close.
            now = time.monotonic()
            if now - self._capacity_warned_at >= 60:
                self._capacity_warned_at = now
                self.log.warning(
                    "Worker at connection capacity, rejecting new connections",
                    extra={"max_connections": self.max_connections},
                )
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
                    on_stream_complete=self._count_request,
                    shutdown_event=self.shutdown_event,
                    keepalive_timeout=self.keepalive_timeout,
                )
                return

        # HTTP/1.1
        await h1.handle_connection(self, conn)

    async def _graceful_shutdown(self) -> None:
        # Wait for in-flight connections with timeout
        if self._connection_tasks:
            from plain.runtime import settings

            timeout = settings.SERVER_GRACEFUL_TIMEOUT
            # The margin is capped at half the window so deliberately
            # short graceful timeouts still get a real drain.
            margin = min(DRAIN_TEARDOWN_MARGIN, timeout / 2)

            deadline = time.monotonic() + timeout
            pending = set(self._connection_tasks)
            while pending:
                # When this shutdown ends in SIGKILL, the arbiter
                # publishes its kill time on the heartbeat — cap the
                # drain so the cancellation and teardown below still run
                # before it lands. Re-read every slice: a deploy can
                # catch a worker that is already draining (e.g.
                # retiring). Retirement SIGTERMs have no SIGKILL
                # follower, publish nothing, and keep the full window.
                kill_deadline = self.heartbeat.kill_deadline()
                if kill_deadline:
                    deadline = min(deadline, kill_deadline - margin)
                    # Tighten in-flight reads to match: a read latched a
                    # longer drain deadline at shutdown start would else
                    # outlive this nearer kill time and die by cancellation
                    # (an RST) instead of finishing with Connection: close.
                    if self.drain_read_deadline is not None:
                        self.drain_read_deadline = min(
                            self.drain_read_deadline, deadline
                        )

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                # Keep the heartbeat fresh while draining so the arbiter
                # doesn't murder a worker that's shutting down normally.
                # (The stalled-pool exit skips this — it stopped
                # heartbeating on purpose to get killed and replaced.)
                if self._notify_during_drain:
                    self.notify()
                _, pending = await asyncio.wait(pending, timeout=min(1.0, remaining))
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending)

        self.tpool.shutdown(wait=False)

    def _begin_drain(self) -> None:
        """Enter graceful shutdown: flip alive, publish the drain state.

        Publishing drain_read_deadline here (not later in run()) means
        in-flight reads are bounded from the instant shutdown starts —
        otherwise a SIGTERM landing while the heartbeat loop is parked
        leaves alive False but the deadline None, and a final-request read
        runs unbounded until _graceful_shutdown cancels it (an RST to the
        client). Idempotent: the first call wins the deadline.
        """
        if self.drain_read_deadline is not None:
            self.alive = False
            self.shutdown_event.set()
            return
        self.alive = False
        self.shutdown_event.set()

        # Derive the read budget from the graceful window (and the
        # arbiter's SIGKILL time when one is published) so a final-request
        # read never outlives the drain and dies by cancellation.
        from plain.runtime import settings

        read_budget = min(DRAIN_READ_TIMEOUT, settings.SERVER_GRACEFUL_TIMEOUT / 4)
        kill_deadline = self.heartbeat.kill_deadline()
        if kill_deadline:
            read_budget = min(
                read_budget,
                max(0.0, kill_deadline - DRAIN_TEARDOWN_MARGIN - time.monotonic()),
            )
        self.drain_read_deadline = time.monotonic() + read_budget

    def _signal_exit(self) -> None:
        self._begin_drain()
        # Immediately stop accepting new connections so requests
        # don't land on a worker that's about to exit (H13 prevention).
        # This runs as an event-loop callback, so the heartbeat loop in
        # run() can resume mid-iteration and observe these servers already
        # closed — per-tick checks on server state would false-positive here.
        for server in self._servers:
            server.close()

    def _signal_quit(self) -> None:
        # Hard stop — the arbiter uses SIGQUIT for immediate termination.
        # Intentionally bypasses _graceful_shutdown. The event is set
        # alongside alive to keep the contract that alive=False implies
        # shutdown_event is set (connection loops watch the event).
        self.alive = False
        self.shutdown_event.set()
        self.tpool.shutdown(wait=False, cancel_futures=True)
        sys.exit(0)

    def handle_abort(self, sig: int, frame: FrameType | None) -> None:
        self.alive = False
        self.shutdown_event.set()
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
            self.log.info(
                "Parent changed, shutting down",
                extra={"worker": str(self)},
            )
            return False
        return True
