from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import base64
import binascii
import datetime
import logging
import time
from typing import TYPE_CHECKING, Any

logging.Logger.manager.emittedNoHandlerWarning = True
import os  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402

from . import util  # noqa: E402

if TYPE_CHECKING:
    from io import TextIOWrapper

    from .config import Config


def loggers() -> list[logging.Logger]:
    """get list of all loggers"""
    root = logging.root
    existing = list(root.manager.loggerDict.keys())
    return [logging.getLogger(name) for name in existing]


class SafeAtoms(dict[str, Any]):
    def __init__(self, atoms: dict[str, Any]) -> None:
        dict.__init__(self)
        for key, value in atoms.items():
            if isinstance(value, str):
                self[key] = value.replace('"', '\\"')
            else:
                self[key] = value

    def __getitem__(self, k: str) -> Any:
        if k.startswith("{"):
            kl = k.lower()
            if kl in self:
                return super().__getitem__(kl)
            else:
                return "-"
        if k in self:
            return super().__getitem__(k)
        else:
            return "-"


class Logger:
    LOG_LEVELS = {
        "critical": logging.CRITICAL,
        "error": logging.ERROR,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG,
    }
    loglevel = logging.INFO

    error_fmt = r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s"
    datefmt = r"[%Y-%m-%d %H:%M:%S %z]"

    access_fmt = "%(message)s"
    syslog_fmt = "[%(process)d] %(message)s"

    atoms_wrapper_class = SafeAtoms

    def __init__(self, cfg: Config) -> None:
        self.error_log = logging.getLogger("plain.server.error")
        self.error_log.propagate = False
        self.access_log = logging.getLogger("plain.server.access")
        self.access_log.propagate = False
        self.error_handlers: list[logging.Handler] = []
        self.access_handlers: list[logging.Handler] = []
        self.logfile: TextIOWrapper | None = None
        self.lock = threading.Lock()
        self.cfg = cfg
        self.setup(cfg)

    def setup(self, cfg: Config) -> None:
        self.loglevel = self.LOG_LEVELS.get(cfg.loglevel.lower(), logging.INFO)
        self.error_log.setLevel(self.loglevel)
        self.access_log.setLevel(logging.INFO)

        # set plain.server.error handler
        self._set_handler(
            self.error_log,
            cfg.errorlog,
            logging.Formatter(cfg.log_format, self.datefmt),
        )

        # set plain.server.access handler
        if cfg.accesslog is not None:
            self._set_handler(
                self.access_log,
                cfg.accesslog,
                fmt=logging.Formatter(cfg.log_format, self.datefmt),
                stream=sys.stdout,
            )

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.error_log.critical(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.error_log.error(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.error_log.warning(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.error_log.info(msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.error_log.debug(msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.error_log.exception(msg, *args, **kwargs)

    def log(self, lvl: int | str, msg: str, *args: Any, **kwargs: Any) -> None:
        if isinstance(lvl, str):
            lvl = self.LOG_LEVELS.get(lvl.lower(), logging.INFO)
        self.error_log.log(lvl, msg, *args, **kwargs)

    def atoms(
        self,
        resp: Any,
        req: Any,
        environ: dict[str, Any],
        request_time: datetime.timedelta,
    ) -> dict[str, Any]:
        """Gets atoms for log formatting."""
        status = resp.status
        if isinstance(status, str):
            status = status.split(None, 1)[0]
        atoms = {
            "h": environ.get("REMOTE_ADDR", "-"),
            "l": "-",
            "u": self._get_user(environ) or "-",
            "t": self.now(),
            "r": "{} {} {}".format(
                environ["REQUEST_METHOD"],
                environ["RAW_URI"],
                environ["SERVER_PROTOCOL"],
            ),
            "s": status,
            "m": environ.get("REQUEST_METHOD"),
            "U": environ.get("PATH_INFO"),
            "q": environ.get("QUERY_STRING"),
            "H": environ.get("SERVER_PROTOCOL"),
            "b": getattr(resp, "sent", None) is not None and str(resp.sent) or "-",
            "B": getattr(resp, "sent", None),
            "f": environ.get("HTTP_REFERER", "-"),
            "a": environ.get("HTTP_USER_AGENT", "-"),
            "T": request_time.seconds,
            "D": (request_time.seconds * 1000000) + request_time.microseconds,
            "M": (request_time.seconds * 1000) + int(request_time.microseconds / 1000),
            "L": f"{request_time.seconds}.{request_time.microseconds:06d}",
            "p": f"<{os.getpid()}>",
        }

        # add request headers
        if hasattr(req, "headers"):
            req_headers = req.headers
        else:
            req_headers = req

        if hasattr(req_headers, "items"):
            req_headers = req_headers.items()

        atoms.update({f"{{{k.lower()}}}i": v for k, v in req_headers})

        resp_headers = resp.headers
        if hasattr(resp_headers, "items"):
            resp_headers = resp_headers.items()

        # add response headers
        atoms.update({f"{{{k.lower()}}}o": v for k, v in resp_headers})

        # add environ variables
        environ_variables = environ.items()
        atoms.update({f"{{{k.lower()}}}e": v for k, v in environ_variables})

        return atoms

    def access(
        self,
        resp: Any,
        req: Any,
        environ: dict[str, Any],
        request_time: datetime.timedelta,
    ) -> None:
        """See http://httpd.apache.org/docs/2.0/logs.html#combined
        for format details
        """

        if not self.cfg.accesslog:
            return None

        # wrap atoms:
        # - make sure atoms will be test case insensitively
        # - if atom doesn't exist replace it by '-'
        safe_atoms = self.atoms_wrapper_class(
            self.atoms(resp, req, environ, request_time)
        )

        try:
            self.access_log.info(self.cfg.access_log_format, safe_atoms)
        except Exception:
            self.error(traceback.format_exc())

        return None

    def now(self) -> str:
        """return date in Apache Common Log Format"""
        return time.strftime("[%d/%b/%Y:%H:%M:%S %z]")

    def reopen_files(self) -> None:
        for log in loggers():
            for handler in log.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.acquire()
                    try:
                        if handler.stream:
                            handler.close()
                            handler.stream = handler._open()
                    finally:
                        handler.release()

    def close_on_exec(self) -> None:
        for log in loggers():
            for handler in log.handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.acquire()
                    try:
                        if handler.stream:
                            util.close_on_exec(handler.stream.fileno())
                    finally:
                        handler.release()

    def _get_plain_server_handler(self, log: logging.Logger) -> logging.Handler | None:
        for h in log.handlers:
            if getattr(h, "_plain_server", False):
                return h
        return None

    def _set_handler(
        self,
        log: logging.Logger,
        output: str | None,
        fmt: logging.Formatter,
        stream: Any = None,
    ) -> None:
        # remove previous plain server log handler
        h = self._get_plain_server_handler(log)
        if h:
            log.handlers.remove(h)

        if output is not None:
            if output == "-":
                h = logging.StreamHandler(stream)
            else:
                util.check_is_writable(output)
                h = logging.FileHandler(output)

            h.setFormatter(fmt)
            h._plain_server = True  # type: ignore[attr-defined]  # custom attribute
            log.addHandler(h)

    def _get_user(self, environ: dict[str, Any]) -> str | None:
        user = None
        http_auth = environ.get("HTTP_AUTHORIZATION")
        if http_auth and http_auth.lower().startswith("basic"):
            auth = http_auth.split(" ", 1)
            if len(auth) == 2:
                try:
                    # b64decode doesn't accept unicode in Python < 3.3
                    # so we need to convert it to a byte string
                    auth = base64.b64decode(auth[1].strip().encode("utf-8"))
                    # b64decode returns a byte string
                    user = auth.split(b":", 1)[0].decode("UTF-8")
                except (TypeError, binascii.Error, UnicodeDecodeError) as exc:
                    self.debug("Couldn't get username: %s", exc)
        return user
