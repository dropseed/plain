from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import os
from dataclasses import dataclass

from . import util
from .workers.sync import SyncWorker
from .workers.thread import ThreadWorker


@dataclass
class Config:
    """Plain server configuration.

    All configuration values are required and provided by the CLI.
    Defaults are defined in the CLI layer, not here.
    """

    # Core settings (from CLI)
    bind: list[str]
    workers: int
    threads: int
    timeout: int
    max_requests: int
    reload: bool
    pidfile: str | None
    certfile: str | None
    keyfile: str | None
    loglevel: str
    accesslog: str
    errorlog: str
    log_format: str
    access_log_format: str

    @property
    def worker_class_str(self) -> str:
        # Auto-select based on threads
        if self.threads > 1:
            return "thread"
        return "sync"

    @property
    def worker_class(self) -> type:
        # Auto-select based on threads
        if self.threads > 1:
            worker_class = ThreadWorker
        else:
            worker_class = SyncWorker

        if hasattr(worker_class, "setup"):
            worker_class.setup()
        return worker_class

    @property
    def address(self) -> list[tuple[str, int] | str]:
        return [util.parse_address(util.bytes_to_str(bind)) for bind in self.bind]

    @property
    def is_ssl(self) -> bool:
        return self.certfile is not None or self.keyfile is not None

    @property
    def sendfile(self) -> bool:
        if "SENDFILE" in os.environ:
            sendfile = os.environ["SENDFILE"].lower()
            return sendfile in ["y", "1", "yes", "true"]

        return True

    @property
    def graceful_timeout(self) -> int:
        """Timeout for graceful worker shutdown in seconds."""
        return 30

    @property
    def forwarded_allow_ips(self) -> list[str]:
        """
        Trusted proxy IPs allowed to set secure headers.
        Default: ['127.0.0.1', '::1'] (localhost only)
        Can be overridden via FORWARDED_ALLOW_IPS environment variable.
        """
        val = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
        return [v.strip() for v in val.split(",") if v]

    @property
    def secure_scheme_headers(self) -> dict[str, str]:
        """
        Headers that indicate HTTPS when set by a trusted proxy.
        Default headers: X-FORWARDED-PROTOCOL, X-FORWARDED-PROTO, X-FORWARDED-SSL
        """
        return {
            "X-FORWARDED-PROTOCOL": "ssl",
            "X-FORWARDED-PROTO": "https",
            "X-FORWARDED-SSL": "on",
        }

    @property
    def forwarder_headers(self) -> list[str]:
        """
        Header names that proxies can use to override WSGI environment.
        Default: ['SCRIPT_NAME', 'PATH_INFO']
        """
        return ["SCRIPT_NAME", "PATH_INFO"]

    @property
    def header_map(self) -> str:
        """
        How to handle header names with underscores.
        Default: 'drop' (silently drop ambiguous headers)
        Options: 'drop', 'refuse', 'dangerous'
        """
        return "drop"
