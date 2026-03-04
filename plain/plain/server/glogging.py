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
import traceback  # noqa: E402

if TYPE_CHECKING:
    from .config import Config


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
    error_fmt = r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s"
    datefmt = r"[%Y-%m-%d %H:%M:%S %z]"

    access_fmt = "%(message)s"
    access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

    atoms_wrapper_class = SafeAtoms

    def __init__(self, cfg: Config) -> None:
        self.error_log = logging.getLogger("plain.server.error")
        self.error_log.propagate = False
        self.access_log = logging.getLogger("plain.server.access")
        self.access_log.propagate = False
        self.cfg = cfg
        self.setup(cfg)

    def setup(self, cfg: Config) -> None:
        self.error_log.setLevel(logging.INFO)
        self.access_log.setLevel(logging.INFO)

        # Error log always goes to stderr
        self._set_handler(
            self.error_log,
            "-",
            logging.Formatter(self.error_fmt, self.datefmt),
        )

        # Access log goes to stdout when enabled
        if cfg.accesslog:
            self._set_handler(
                self.access_log,
                "-",
                fmt=logging.Formatter(self.access_fmt),
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

    def atoms(
        self,
        resp: Any,
        req: Any,
        request_time: datetime.timedelta,
    ) -> dict[str, Any]:
        """Gets atoms for log formatting.

        req is the server's parsed HTTP message (always present).
        """
        status = resp.status
        if isinstance(status, str):
            status = status.split(None, 1)[0]

        protocol = f"HTTP/{req.version[0]}.{req.version[1]}"

        # Get client IP from the server request's peer address
        if isinstance(req.peer_addr, tuple):
            remote_addr = req.peer_addr[0]
        elif isinstance(req.peer_addr, str):
            remote_addr = req.peer_addr
        else:
            remote_addr = "-"

        atoms: dict[str, Any] = {}

        # Add request headers as {name}i atoms
        atoms.update({f"{{{k.lower()}}}i": v for k, v in req.headers})

        # Add response headers as {name}o atoms
        resp_headers = resp.headers
        if hasattr(resp_headers, "items"):
            resp_headers = resp_headers.items()
        atoms.update({f"{{{k.lower()}}}o": v for k, v in resp_headers})

        atoms.update(
            {
                "h": remote_addr,
                "l": "-",
                "u": self._get_user(atoms) or "-",
                "t": self.now(),
                "r": f"{req.method} {req.uri} {protocol}",
                "s": status,
                "m": req.method,
                "U": req.path,
                "q": req.query,
                "H": protocol,
                "b": getattr(resp, "sent", None) is not None and str(resp.sent) or "-",
                "B": getattr(resp, "sent", None),
                "f": atoms.get("{referer}i", "-"),
                "a": atoms.get("{user-agent}i", "-"),
                "T": request_time.seconds,
                "D": (request_time.seconds * 1000000) + request_time.microseconds,
                "M": (request_time.seconds * 1000)
                + int(request_time.microseconds / 1000),
                "L": f"{request_time.seconds}.{request_time.microseconds:06d}",
                "p": f"<{os.getpid()}>",
            }
        )

        return atoms

    def access(
        self,
        resp: Any,
        req: Any,
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
        safe_atoms = self.atoms_wrapper_class(self.atoms(resp, req, request_time))

        try:
            self.access_log.info(self.access_log_format, safe_atoms)
        except Exception:
            self.error(traceback.format_exc())

        return None

    def now(self) -> str:
        """return date in Apache Common Log Format"""
        return time.strftime("[%d/%b/%Y:%H:%M:%S %z]")

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
            h = logging.StreamHandler(stream)
            h.setFormatter(fmt)
            h._plain_server = True  # type: ignore[attr-defined]  # custom attribute
            log.addHandler(h)

    def _get_user(self, atoms: dict[str, Any]) -> str | None:
        """Extract username from Basic auth in request headers."""
        user = None
        http_auth = atoms.get("{authorization}i")
        if http_auth and http_auth.lower().startswith("basic"):
            auth = http_auth.split(" ", 1)
            if len(auth) == 2:
                try:
                    auth = base64.b64decode(auth[1].strip().encode("utf-8"))
                    user = auth.split(b":", 1)[0].decode("UTF-8")
                except (TypeError, binascii.Error, UnicodeDecodeError) as exc:
                    self.debug("Couldn't get username: %s", exc)
        return user
