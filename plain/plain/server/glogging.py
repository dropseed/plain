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
import os
import sys
import time
import traceback
from typing import Any

# Module-level loggers
log = logging.getLogger("plain.server")
access_log = logging.getLogger("plain.server.access")

# Access log format (Apache Combined Log Format)
ACCESS_LOG_FORMAT = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'


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


def setup_bootstrap_logging(accesslog: bool) -> None:
    """Set up minimal logging before fork.

    Provides basic stderr/stdout handlers so the arbiter can log
    before the full plain.logs configuration runs in worker processes.
    """
    log.setLevel(logging.INFO)
    log.propagate = False
    access_log.setLevel(logging.INFO)
    access_log.propagate = False

    # Error log always goes to stderr
    _set_handler(
        log,
        logging.Formatter(
            r"%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
            r"[%Y-%m-%d %H:%M:%S %z]",
        ),
    )

    # Access log goes to stdout when enabled
    if accesslog:
        _set_handler(
            access_log,
            logging.Formatter("%(message)s"),
            stream=sys.stdout,
        )


def _set_handler(
    logger: logging.Logger,
    fmt: logging.Formatter,
    stream: Any = None,
) -> None:
    """Replace any existing plain server handler on the logger."""
    for h in logger.handlers[:]:
        if getattr(h, "_plain_server", False):
            logger.handlers.remove(h)

    h = logging.StreamHandler(stream)
    h.setFormatter(fmt)
    h._plain_server = True  # type: ignore[attr-defined]
    logger.addHandler(h)


def log_access(
    resp: Any,
    req: Any,
    request_time: datetime.timedelta,
) -> None:
    """Log an access entry for a completed request."""
    if not access_log.handlers:
        return

    safe_atoms = SafeAtoms(_build_atoms(resp, req, request_time))

    try:
        access_log.info(ACCESS_LOG_FORMAT, safe_atoms)
    except Exception:
        log.error(traceback.format_exc())


def _build_atoms(
    resp: Any,
    req: Any,
    request_time: datetime.timedelta,
) -> dict[str, Any]:
    """Build log atoms from server response and request objects."""
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
            "u": _get_user(atoms) or "-",
            "t": time.strftime("[%d/%b/%Y:%H:%M:%S %z]"),
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
            "M": (request_time.seconds * 1000) + int(request_time.microseconds / 1000),
            "L": f"{request_time.seconds}.{request_time.microseconds:06d}",
            "p": f"<{os.getpid()}>",
        }
    )

    return atoms


def _get_user(atoms: dict[str, Any]) -> str | None:
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
                log.debug("Couldn't get username: %s", exc)
    return user
