from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import errno
import logging
import multiprocessing
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import plain.runtime
from plain.runtime import settings

from . import sock
from .errors import APP_LOAD_ERROR, WORKER_BOOT_ERROR, HaltServer
from .workers.entry import worker_main
from .workers.worker import check_worker_config
from .workers.workertmp import WorkerHeartbeat

if TYPE_CHECKING:
    from .app import ServerApplication


@dataclass
class WorkerInfo:
    process: multiprocessing.process.BaseProcess
    heartbeat: WorkerHeartbeat
    age: int
    spawned_at: float = field(default_factory=time.monotonic)
    aborted: bool = field(default=False)


class Arbiter:
    """
    Arbiter maintains the worker processes alive. It launches or
    kills them if needed.
    """

    def __init__(self, app: ServerApplication):
        os.environ["SERVER_SOFTWARE"] = f"plain/{plain.runtime.__version__}"

        self.app = app
        self.log: logging.Logger = logging.getLogger("plain.server")
        self.num_workers: int = app.workers
        self.timeout: int = app.timeout
        self.pid: int = os.getpid()
        self.worker_age: int = 0
        self._workers: dict[int, WorkerInfo] = {}
        self._listeners: list[sock.BaseSocket] = []
        self._shutdown_event = threading.Event()
        self._graceful_shutdown = True
        self._halt_error: HaltServer | None = None
        self._last_logged_active_worker_count: int | None = None
        self._mp_context = multiprocessing.get_context("spawn")

    def run(self) -> None:
        """Main supervisor loop."""
        self._start()

        try:
            self.manage_workers()

            while not self._shutdown_event.is_set():
                self.reap_workers()
                if self._halt_error:
                    raise self._halt_error
                self.murder_workers()
                self.manage_workers()
                self._shutdown_event.wait(timeout=1.0)

            self._halt(graceful=self._graceful_shutdown)
        except KeyboardInterrupt:
            self._halt(graceful=False)
        except HaltServer as inst:
            self._halt(reason=inst.reason, exit_status=inst.exit_status)
        except SystemExit:
            raise
        except Exception:
            self.log.error("Unhandled exception in main loop", exc_info=True)
            self._stop(graceful=False)
            sys.exit(-1)

    def _start(self) -> None:
        """Initialize the arbiter. Start listening."""
        # SIGTERM = graceful shutdown, SIGINT/SIGQUIT = immediate shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_hard_stop)
        signal.signal(signal.SIGQUIT, self._handle_hard_stop)

        self._listeners = sock.create_sockets(self.app)

        listeners_str = ",".join([str(lnr) for lnr in self._listeners])
        self.log.info(
            "Plain server started address=%s pid=%s workers=%s threads=%s version=%s",
            listeners_str,
            self.pid,
            self.num_workers,
            self.app.threads,
            plain.runtime.__version__,
        )

        from plain.runtime import settings

        check_worker_config(self.app.threads, settings.SERVER_CONNECTIONS, self.log)

    def _handle_signal(self, sig: int, frame: object) -> None:
        self._shutdown_event.set()

    def _handle_hard_stop(self, sig: int, frame: object) -> None:
        self._graceful_shutdown = False
        self._shutdown_event.set()

    def _halt(
        self, reason: str | None = None, exit_status: int = 0, graceful: bool = True
    ) -> None:
        """Halt arbiter."""
        self._stop(graceful=graceful)

        log_func = self.log.info if exit_status == 0 else self.log.error
        log_func("Shutting down: Master")
        if reason is not None:
            log_func("Reason: %s", reason)

        sys.exit(exit_status)

    def _stop(self, graceful: bool = True) -> None:
        """Stop workers."""
        sock.close_sockets(self._listeners, unlink=True)
        self._listeners = []

        sig = signal.SIGTERM if graceful else signal.SIGQUIT
        limit = time.time() + settings.SERVER_GRACEFUL_TIMEOUT

        # Instruct the workers to exit
        self._kill_workers(sig)

        # Wait until the graceful timeout
        while self._workers and time.time() < limit:
            self.reap_workers()
            time.sleep(0.1)

        self._kill_workers(signal.SIGKILL)

        # Join and close all remaining processes
        for pid in list(self._workers):
            info = self._workers.pop(pid)
            info.process.join(timeout=5)
            info.heartbeat.close()
            info.process.close()

    def murder_workers(self) -> None:
        """Kill workers that have stopped heartbeating."""
        if not self.timeout:
            return

        now = time.monotonic()
        for pid, info in list(self._workers.items()):
            # Don't kill workers that haven't had enough time to boot
            # and start heartbeating (spawn is slower than fork).
            if now - info.spawned_at < self.timeout:
                continue

            try:
                if now - info.heartbeat.last_update() <= self.timeout:
                    continue
            except (OSError, ValueError):
                continue

            if not info.aborted:
                self.log.critical("WORKER TIMEOUT (pid:%s)", pid)
                info.aborted = True
                self._kill_worker(pid, signal.SIGABRT)
            else:
                self._kill_worker(pid, signal.SIGKILL)

    def reap_workers(self) -> None:
        """
        Reap dead workers and log exit reasons.
        Sets self._halt_error if a worker failed to boot.
        """
        for pid in list(self._workers):
            info = self._workers[pid]
            if info.process.is_alive():
                continue

            exitcode = info.process.exitcode
            if exitcode is None:
                continue

            if exitcode > 0:
                self.log.error("Worker (pid:%s) exited with code %s", pid, exitcode)

            if exitcode == WORKER_BOOT_ERROR and self._halt_error is None:
                self._halt_error = HaltServer(
                    "Worker failed to boot.", WORKER_BOOT_ERROR
                )
            elif exitcode == APP_LOAD_ERROR and self._halt_error is None:
                self._halt_error = HaltServer("App failed to load.", APP_LOAD_ERROR)
            elif exitcode < 0:
                # Negative exit codes mean the worker was killed by a signal
                try:
                    sig_name = signal.Signals(-exitcode).name
                except ValueError:
                    sig_name = f"signal {-exitcode}"
                msg = f"Worker (pid:{pid}) was sent {sig_name}!"
                if -exitcode == signal.SIGKILL:
                    msg += " Perhaps out of memory?"
                if -exitcode == signal.SIGTERM:
                    self.log.info(msg)
                else:
                    self.log.error(msg)

            info.heartbeat.close()
            info.process.join(timeout=0)
            info.process.close()
            del self._workers[pid]

    def manage_workers(self) -> None:
        """Maintain the number of workers by spawning or killing as required."""
        while len(self._workers) < self.num_workers:
            self._spawn_worker()

        if len(self._workers) > self.num_workers:
            workers = sorted(self._workers.items(), key=lambda w: w[1].age)
            while len(workers) > self.num_workers:
                (pid, _) = workers.pop(0)
                self._kill_worker(pid, signal.SIGTERM)

        active_worker_count = len(self._workers)
        if self._last_logged_active_worker_count != active_worker_count:
            self._last_logged_active_worker_count = active_worker_count
            self.log.debug(
                f"{active_worker_count} workers",
                extra={
                    "metric": "plain.server.workers",
                    "value": active_worker_count,
                    "mtype": "gauge",
                },
            )

    def _spawn_worker(self) -> None:
        self.worker_age += 1
        heartbeat = WorkerHeartbeat(self._mp_context)

        # Serialize listener info for the spawned process.
        # Raw socket objects are pickled via multiprocessing (SCM_RIGHTS on Unix).
        listener_data = [
            (listener.sock, listener.cfg_addr, listener.FAMILY, listener.is_ssl)
            for listener in self._listeners
        ]

        process = self._mp_context.Process(
            target=worker_main,
            args=(
                self.worker_age,
                listener_data,
                self.app,
                self.timeout / 2.0,
                heartbeat,
            ),
        )
        process.start()
        assert process.pid is not None
        self._workers[process.pid] = WorkerInfo(process, heartbeat, self.worker_age)

    def _kill_workers(self, sig: int) -> None:
        """Kill all workers with the signal `sig`."""
        for pid in list(self._workers.keys()):
            self._kill_worker(pid, sig)

    def _kill_worker(self, pid: int, sig: int) -> None:
        """Kill a worker."""
        try:
            os.kill(pid, sig)
        except OSError as e:
            if e.errno == errno.ESRCH:
                try:
                    info = self._workers.pop(pid)
                    info.heartbeat.close()
                    info.process.close()
                except (KeyError, OSError):
                    pass
                return
            raise
