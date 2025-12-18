from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import io
import os
import signal
import sys
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from random import randint
from ssl import SSLError
from typing import TYPE_CHECKING, Any

from plain.internal.reloader import Reloader

from .. import sock, util
from ..http.errors import (
    ConfigurationProblem,
    InvalidHeader,
    InvalidHeaderName,
    InvalidHTTPVersion,
    InvalidRequestLine,
    InvalidRequestMethod,
    InvalidSchemeHeaders,
    LimitRequestHeaders,
    LimitRequestLine,
    ObsoleteFolding,
    UnsupportedTransferCoding,
)
from ..http.wsgi import Response, default_environ
from .workertmp import WorkerTmp

if TYPE_CHECKING:
    import socket

    from ..app import ServerApplication
    from ..config import Config
    from ..glogging import Logger
    from ..http.message import Request

# Maximum jitter to add to max_requests to stagger worker restarts
MAX_REQUESTS_JITTER = 50


class Worker(ABC):
    SIGNALS = [
        getattr(signal, f"SIG{x}")
        for x in ("ABRT HUP QUIT INT TERM USR1 USR2 WINCH CHLD".split())
    ]

    PIPE = []

    def __init__(
        self,
        age: int,
        ppid: int,
        sockets: list[sock.BaseSocket],
        app: ServerApplication,
        timeout: int | float,
        cfg: Config,
        log: Logger,
    ):
        """\
        This is called pre-fork so it shouldn't do anything to the
        current process. If there's a need to make process wide
        changes you'll want to do that in ``self.init_process()``.
        """
        self.age = age
        self.pid: str | int = "[booting]"
        self.ppid = ppid
        self.sockets = sockets
        self.app = app
        self.timeout = timeout
        self.cfg = cfg
        self.booted = False
        self.aborted = False
        self.reloader: Any = None

        self.nr = 0

        if cfg.max_requests > 0:
            jitter = randint(0, MAX_REQUESTS_JITTER)
            self.max_requests = cfg.max_requests + jitter
        else:
            self.max_requests = sys.maxsize

        self.alive = True
        self.log = log
        self.tmp = WorkerTmp(cfg)

    def __str__(self) -> str:
        return f"<Worker {self.pid}>"

    def notify(self) -> None:
        """\
        Your worker subclass must arrange to have this method called
        once every ``self.timeout`` seconds. If you fail in accomplishing
        this task, the master process will murder your workers.
        """
        self.tmp.notify()

    @abstractmethod
    def run(self) -> None:
        """\
        This is the mainloop of a worker process. You should override
        this method in a subclass to provide the intended behaviour
        for your particular evil schemes.
        """
        ...

    def init_process(self) -> None:
        """\
        If you override this method in a subclass, the last statement
        in the function should be to call this method with
        super().init_process() so that the ``run()`` loop is initiated.
        """

        # Reseed the random number generator
        util.seed()

        # For waking ourselves up
        self.PIPE = os.pipe()
        for p in self.PIPE:
            util.set_non_blocking(p)
            util.close_on_exec(p)

        # Prevent fd inheritance
        for s in self.sockets:
            util.close_on_exec(s.fileno())
        util.close_on_exec(self.tmp.fileno())

        self.wait_fds: list[sock.BaseSocket | int] = self.sockets + [self.PIPE[0]]

        self.log.close_on_exec()

        self.init_signals()

        # start the reloader
        if self.cfg.reload:

            def changed(fname: str) -> None:
                self.log.debug("Server worker reloading: %s modified", fname)
                self.alive = False
                os.write(self.PIPE[1], b"1")
                time.sleep(0.1)
                sys.exit(0)

            self.reloader = Reloader(callback=changed, watch_html=True)

        self.load_wsgi()
        if self.reloader:
            self.reloader.start()

        # Enter main run loop
        self.booted = True
        self.run()

    def load_wsgi(self) -> None:
        try:
            self.wsgi = self.app.wsgi()
        except SyntaxError:
            if not self.cfg.reload:
                raise

            self.log.exception("Error loading WSGI application")

            # fix from PR #1228
            # storing the traceback into exc_tb will create a circular reference.
            # per https://docs.python.org/2/library/sys.html#sys.exc_info warning,
            # delete the traceback after use.
            try:
                _, exc_val, exc_tb = sys.exc_info()

                tb_string = io.StringIO()
                traceback.print_tb(exc_tb, file=tb_string)
                self.wsgi = util.make_fail_app(tb_string.getvalue())
            finally:
                del exc_tb

    def init_signals(self) -> None:
        # reset signaling
        for s in self.SIGNALS:
            signal.signal(s, signal.SIG_DFL)
        # init new signaling
        signal.signal(signal.SIGQUIT, self.handle_quit)
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_quit)
        signal.signal(signal.SIGWINCH, self.handle_winch)
        signal.signal(signal.SIGUSR1, self.handle_usr1)
        signal.signal(signal.SIGABRT, self.handle_abort)

        # Don't let SIGTERM and SIGUSR1 disturb active requests
        # by interrupting system calls
        signal.siginterrupt(signal.SIGTERM, False)
        signal.siginterrupt(signal.SIGUSR1, False)

        if hasattr(signal, "set_wakeup_fd"):
            signal.set_wakeup_fd(self.PIPE[1])

    def handle_usr1(self, sig: int, frame: Any) -> None:
        self.log.reopen_files()

    def handle_exit(self, sig: int, frame: Any) -> None:
        self.alive = False

    def handle_quit(self, sig: int, frame: Any) -> None:
        self.alive = False
        time.sleep(0.1)
        sys.exit(0)

    def handle_abort(self, sig: int, frame: Any) -> None:
        self.alive = False
        sys.exit(1)

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
            | LimitRequestLine
            | LimitRequestHeaders
            | InvalidSchemeHeaders
            | UnsupportedTransferCoding
            | ConfigurationProblem
            | ObsoleteFolding
            | SSLError,
        ):
            status_int = 400
            reason = "Bad Request"

            if isinstance(exc, InvalidRequestLine):
                mesg = f"Invalid Request Line '{str(exc)}'"
            elif isinstance(exc, InvalidRequestMethod):
                mesg = f"Invalid Method '{str(exc)}'"
            elif isinstance(exc, InvalidHTTPVersion):
                mesg = f"Invalid HTTP Version '{str(exc)}'"
            elif isinstance(exc, UnsupportedTransferCoding):
                mesg = f"{str(exc)}"
                status_int = 501
            elif isinstance(exc, ConfigurationProblem):
                mesg = f"{str(exc)}"
                status_int = 500
            elif isinstance(exc, ObsoleteFolding):
                mesg = f"{str(exc)}"
            elif isinstance(exc, InvalidHeaderName | InvalidHeader):
                mesg = f"{str(exc)}"
                if not req and hasattr(exc, "req"):
                    req = exc.req  # type: ignore[assignment]  # for access log
            elif isinstance(exc, LimitRequestLine):
                mesg = f"{str(exc)}"
            elif isinstance(exc, LimitRequestHeaders):
                reason = "Request Header Fields Too Large"
                mesg = f"Error parsing headers: '{str(exc)}'"
                status_int = 431
            elif isinstance(exc, InvalidSchemeHeaders):
                mesg = f"{str(exc)}"
            elif isinstance(exc, SSLError):
                reason = "Forbidden"
                mesg = f"'{str(exc)}'"
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
            environ = default_environ(req, client, self.cfg)
            environ["REMOTE_ADDR"] = addr[0]
            environ["REMOTE_PORT"] = str(addr[1])
            resp = Response(req, client, self.cfg)
            resp.status = f"{status_int} {reason}"
            resp.response_length = len(mesg)
            self.log.access(resp, req, environ, request_time)

        try:
            util.write_error(client, status_int, reason, mesg)
        except Exception:
            self.log.debug("Failed to send error message.")

    def handle_winch(self, sig: int, fname: Any) -> None:
        # Ignore SIGWINCH in worker. Fixes a crash on OpenBSD.
        self.log.debug("worker: SIGWINCH ignored.")
