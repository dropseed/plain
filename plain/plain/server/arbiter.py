from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import errno
import os
import random
import select
import signal
import sys
import time
import traceback
from types import FrameType
from typing import TYPE_CHECKING, Any

import plain.runtime

from . import sock, util
from .errors import AppImportError, HaltServer
from .pidfile import Pidfile

if TYPE_CHECKING:
    from .app import ServerApplication
    from .config import Config
    from .glogging import Logger
    from .workers.base import Worker


class Arbiter:
    """
    Arbiter maintain the workers processes alive. It launches or
    kills them if needed. It also manages application reloading
    via SIGHUP.
    """

    # A flag indicating if a worker failed to
    # to boot. If a worker process exist with
    # this error code, the arbiter will terminate.
    WORKER_BOOT_ERROR: int = 3

    # A flag indicating if an application failed to be loaded
    APP_LOAD_ERROR: int = 4

    START_CTX: dict[int | str, Any] = {}

    LISTENERS: list[sock.BaseSocket] = []
    WORKERS: dict[int, Worker] = {}
    PIPE: list[int] = []

    # I love dynamic languages
    SIG_QUEUE: list[int] = []
    SIGNALS: list[int] = [
        getattr(signal, f"SIG{x}")
        for x in "HUP QUIT INT TERM TTIN TTOU USR1 USR2 WINCH".split()
    ]
    SIG_NAMES: dict[int, str] = {
        getattr(signal, name): name[3:].lower()
        for name in dir(signal)
        if name[:3] == "SIG" and name[3] != "_"
    }

    def __init__(self, app: ServerApplication):
        os.environ["SERVER_SOFTWARE"] = f"plain/{plain.runtime.__version__}"

        self._num_workers: int | None = None
        self._last_logged_active_worker_count: int | None = None

        self.setup(app)

        self.pidfile: Pidfile | None = None
        self.worker_age: int = 0

        cwd = util.getcwd()

        args = sys.argv[:]
        args.insert(0, sys.executable)

        # init start context
        self.START_CTX = {"args": args, "cwd": cwd, 0: sys.executable}

    def _get_num_workers(self) -> int:
        assert self._num_workers is not None, "num_workers not initialized"
        return self._num_workers

    def _set_num_workers(self, value: int) -> None:
        self._num_workers = value

    num_workers = property(_get_num_workers, _set_num_workers)

    def setup(self, app: ServerApplication) -> None:
        self.app: ServerApplication = app
        assert app.cfg is not None, "Application config must be initialized"
        self.cfg: Config = app.cfg

        if not hasattr(self, "log"):
            from .glogging import Logger

            self.log: Logger = Logger(self.cfg)

        self.worker_class: type[Worker] = self.cfg.worker_class
        self.address: str = self.cfg.address
        self.num_workers = self.cfg.workers
        self.timeout: int = self.cfg.timeout

    def start(self) -> None:
        """\
        Initialize the arbiter. Start listening and set pidfile if needed.
        """
        self.pid: int = os.getpid()
        if self.cfg.pidfile is not None:
            self.pidfile = Pidfile(self.cfg.pidfile)
            self.pidfile.create(self.pid)

        self.init_signals()

        if not self.LISTENERS:
            self.LISTENERS = sock.create_sockets(self.cfg, self.log)

        listeners_str = ",".join([str(lnr) for lnr in self.LISTENERS])
        self.log.info(
            "Plain server started address=%s pid=%s worker=%s version=%s",
            listeners_str,
            self.pid,
            self.cfg.worker_class_str,
            plain.runtime.__version__,
        )

        # check worker class requirements
        if check_config := getattr(self.worker_class, "check_config", None):
            check_config(self.cfg, self.log)

    def init_signals(self) -> None:
        """\
        Initialize master signal handling. Most of the signals
        are queued. Child signals only wake up the master.
        """
        # close old PIPE
        for p in self.PIPE:
            os.close(p)

        # initialize the pipe
        pair = os.pipe()
        self.PIPE = list(pair)
        for p in pair:
            util.set_non_blocking(p)
            util.close_on_exec(p)

        self.log.close_on_exec()

        # initialize all signals
        for s in self.SIGNALS:
            signal.signal(s, self.signal)
        signal.signal(signal.SIGCHLD, self.handle_chld)

    def signal(self, sig: int, frame: FrameType | None) -> None:
        if len(self.SIG_QUEUE) < 5:
            self.SIG_QUEUE.append(sig)
            self.wakeup()

    def run(self) -> None:
        "Main master loop."
        self.start()

        try:
            self.manage_workers()

            while True:
                sig = self.SIG_QUEUE.pop(0) if self.SIG_QUEUE else None
                if sig is None:
                    self.sleep()
                    self.murder_workers()
                    self.manage_workers()
                    continue

                if sig not in self.SIG_NAMES:
                    self.log.info("Ignoring unknown signal: %s", sig)
                    continue

                signame = self.SIG_NAMES.get(sig)
                handler = getattr(self, f"handle_{signame}", None)
                if not handler:
                    self.log.error("Unhandled signal: %s", signame)
                    continue
                self.log.info("Handling signal: %s", signame)
                handler()
                self.wakeup()
        except (StopIteration, KeyboardInterrupt):
            self.halt()
        except HaltServer as inst:
            self.halt(reason=inst.reason, exit_status=inst.exit_status)
        except SystemExit:
            raise
        except Exception:
            self.log.error("Unhandled exception in main loop", exc_info=True)
            self.stop(False)
            if self.pidfile is not None:
                self.pidfile.unlink()
            sys.exit(-1)

    def handle_chld(self, sig: int, frame: FrameType | None) -> None:
        "SIGCHLD handling"
        self.reap_workers()
        self.wakeup()

    def handle_hup(self) -> None:
        """\
        HUP handling.
        - Reload configuration
        - Start the new worker processes with a new configuration
        - Gracefully shutdown the old worker processes
        """
        self.log.info("Hang up: Master")
        self.reload()

    def handle_term(self) -> None:
        "SIGTERM handling"
        raise StopIteration

    def handle_int(self) -> None:
        "SIGINT handling"
        self.stop(False)
        raise StopIteration

    def handle_quit(self) -> None:
        "SIGQUIT handling"
        self.stop(False)
        raise StopIteration

    def handle_ttin(self) -> None:
        """\
        SIGTTIN handling.
        Increases the number of workers by one.
        """
        self.num_workers += 1
        self.manage_workers()

    def handle_ttou(self) -> None:
        """\
        SIGTTOU handling.
        Decreases the number of workers by one.
        """
        if self.num_workers <= 1:
            return None
        self.num_workers -= 1
        self.manage_workers()

    def handle_usr1(self) -> None:
        """\
        SIGUSR1 handling.
        Kill all workers by sending them a SIGUSR1
        """
        self.log.reopen_files()
        self.kill_workers(signal.SIGUSR1)

    def handle_usr2(self) -> None:
        """SIGUSR2 handling"""
        # USR2 for graceful restart is not supported
        self.log.debug("SIGUSR2 ignored")

    def handle_winch(self) -> None:
        """SIGWINCH handling"""
        # SIGWINCH is typically used to gracefully stop workers when running as daemon
        # Since we don't support daemon mode, just log that it's ignored
        self.log.debug("SIGWINCH ignored")

    def wakeup(self) -> None:
        """\
        Wake up the arbiter by writing to the PIPE
        """
        try:
            os.write(self.PIPE[1], b".")
        except OSError as e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise

    def halt(self, reason: str | None = None, exit_status: int = 0) -> None:
        """halt arbiter"""
        self.stop()

        log_func = self.log.info if exit_status == 0 else self.log.error
        log_func("Shutting down: Master")
        if reason is not None:
            log_func("Reason: %s", reason)

        if self.pidfile is not None:
            self.pidfile.unlink()
        sys.exit(exit_status)

    def sleep(self) -> None:
        """\
        Sleep until PIPE is readable or we timeout.
        A readable PIPE means a signal occurred.
        """
        try:
            ready = select.select([self.PIPE[0]], [], [], 1.0)
            if not ready[0]:
                return
            while os.read(self.PIPE[0], 1):
                pass
        except OSError as e:
            # TODO: select.error is a subclass of OSError since Python 3.3.
            error_number = getattr(e, "errno", e.args[0])
            if error_number not in [errno.EAGAIN, errno.EINTR]:
                raise
        except KeyboardInterrupt:
            sys.exit()

    def stop(self, graceful: bool = True) -> None:
        """\
        Stop workers

        :attr graceful: boolean, If True (the default) workers will be
        killed gracefully  (ie. trying to wait for the current connection)
        """
        sock.close_sockets(self.LISTENERS, unlink=True)

        self.LISTENERS = []
        sig = signal.SIGTERM
        if not graceful:
            sig = signal.SIGQUIT
        limit = time.time() + self.cfg.graceful_timeout
        # instruct the workers to exit
        self.kill_workers(sig)
        # wait until the graceful timeout
        while self.WORKERS and time.time() < limit:
            time.sleep(0.1)

        self.kill_workers(signal.SIGKILL)

    def reload(self) -> None:
        old_address = self.cfg.address

        self.setup(self.app)

        # reopen log files
        self.log.reopen_files()

        # do we need to change listener ?
        if old_address != self.cfg.address:
            # close all listeners
            for lnr in self.LISTENERS:
                lnr.close()
            # init new listeners
            self.LISTENERS = sock.create_sockets(self.cfg, self.log)
            listeners_str = ",".join([str(lnr) for lnr in self.LISTENERS])
            self.log.info("Listening at: %s", listeners_str)

        # unlink pidfile
        if self.pidfile is not None:
            self.pidfile.unlink()

        # create new pidfile
        if self.cfg.pidfile is not None:
            self.pidfile = Pidfile(self.cfg.pidfile)
            self.pidfile.create(self.pid)

        # spawn new workers
        for _ in range(self.cfg.workers):
            self.spawn_worker()

        # manage workers
        self.manage_workers()

    def murder_workers(self) -> None:
        """\
        Kill unused/idle workers
        """
        if not self.timeout:
            return None
        workers = list(self.WORKERS.items())
        for pid, worker in workers:
            try:
                if time.monotonic() - worker.tmp.last_update() <= self.timeout:
                    continue
            except (OSError, ValueError):
                continue

            if not worker.aborted:
                self.log.critical("WORKER TIMEOUT (pid:%s)", pid)
                worker.aborted = True
                self.kill_worker(pid, signal.SIGABRT)
            else:
                self.kill_worker(pid, signal.SIGKILL)

    def reap_workers(self) -> None:
        """\
        Reap workers to avoid zombie processes
        """
        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if not wpid:
                    break

                # A worker was terminated. If the termination reason was
                # that it could not boot, we'll shut it down to avoid
                # infinite start/stop cycles.
                exitcode = status >> 8
                if exitcode != 0:
                    self.log.error(
                        "Worker (pid:%s) exited with code %s", wpid, exitcode
                    )
                if exitcode == self.WORKER_BOOT_ERROR:
                    reason = "Worker failed to boot."
                    raise HaltServer(reason, self.WORKER_BOOT_ERROR)
                if exitcode == self.APP_LOAD_ERROR:
                    reason = "App failed to load."
                    raise HaltServer(reason, self.APP_LOAD_ERROR)

                if exitcode > 0:
                    # If the exit code of the worker is greater than 0,
                    # let the user know.
                    self.log.error(
                        "Worker (pid:%s) exited with code %s.", wpid, exitcode
                    )
                elif status > 0:
                    # If the exit code of the worker is 0 and the status
                    # is greater than 0, then it was most likely killed
                    # via a signal.
                    try:
                        sig_name = signal.Signals(status).name
                    except ValueError:
                        sig_name = f"code {status}"
                    msg = f"Worker (pid:{wpid}) was sent {sig_name}!"

                    # Additional hint for SIGKILL
                    if status == signal.SIGKILL:
                        msg += " Perhaps out of memory?"
                    self.log.error(msg)

                worker = self.WORKERS.pop(wpid, None)
                if not worker:
                    continue
                worker.tmp.close()
        except OSError as e:
            if e.errno != errno.ECHILD:
                raise

    def manage_workers(self) -> None:
        """\
        Maintain the number of workers by spawning or killing
        as required.
        """
        if len(self.WORKERS) < self.num_workers:
            self.spawn_workers()

        workers = self.WORKERS.items()
        workers = sorted(workers, key=lambda w: w[1].age)
        while len(workers) > self.num_workers:
            (pid, _) = workers.pop(0)
            self.kill_worker(pid, signal.SIGTERM)

        active_worker_count = len(workers)
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

    def spawn_worker(self) -> int:
        self.worker_age += 1
        worker = self.worker_class(
            self.worker_age,
            self.pid,
            self.LISTENERS,
            self.app,
            self.timeout / 2.0,
            self.cfg,
            self.log,
        )
        pid = os.fork()
        if pid != 0:
            worker.pid = pid
            self.WORKERS[pid] = worker
            return pid

        # Do not inherit the temporary files of other workers
        for sibling in self.WORKERS.values():
            sibling.tmp.close()

        # Process Child
        worker.pid = os.getpid()
        try:
            self.log.info("Server worker started pid=%s", worker.pid)
            worker.init_process()
            sys.exit(0)
        except SystemExit:
            raise
        except AppImportError as e:
            self.log.debug("Exception while loading the application", exc_info=True)
            print(f"{e}", file=sys.stderr)
            sys.stderr.flush()
            sys.exit(self.APP_LOAD_ERROR)
        except Exception:
            self.log.exception("Exception in worker process")
            if not worker.booted:
                sys.exit(self.WORKER_BOOT_ERROR)
            sys.exit(-1)
        finally:
            self.log.info("Server worker exiting (pid: %s)", worker.pid)
            try:
                worker.tmp.close()
            except Exception:
                self.log.warning(
                    "Exception during worker exit:\n%s", traceback.format_exc()
                )

    def spawn_workers(self) -> None:
        """\
        Spawn new workers as needed.

        This is where a worker process leaves the main loop
        of the master process.
        """

        for _ in range(self.num_workers - len(self.WORKERS)):
            self.spawn_worker()
            time.sleep(0.1 * random.random())

    def kill_workers(self, sig: int) -> None:
        """\
        Kill all workers with the signal `sig`
        :attr sig: `signal.SIG*` value
        """
        worker_pids = list(self.WORKERS.keys())
        for pid in worker_pids:
            self.kill_worker(pid, sig)

    def kill_worker(self, pid: int, sig: int) -> None:
        """\
        Kill a worker

        :attr pid: int, worker pid
        :attr sig: `signal.SIG*` value
         """
        try:
            os.kill(pid, sig)
        except OSError as e:
            if e.errno == errno.ESRCH:
                try:
                    worker = self.WORKERS.pop(pid)
                    worker.tmp.close()
                    return None
                except (KeyError, OSError):
                    return None
            raise
