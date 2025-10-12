from __future__ import annotations

#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.
import os
from dataclasses import dataclass, field

from . import util


@dataclass
class Config:
    """Plain server configuration."""

    # Core settings (from CLI)
    bind: list[str] = field(default_factory=lambda: ["127.0.0.1:8000"])
    workers: int = 1
    threads: int = 1
    timeout: int = 30
    max_requests: int = 0
    reload: bool = False
    reload_extra_files: list[str] = field(default_factory=list)
    pidfile: str | None = None
    certfile: str | None = None
    keyfile: str | None = None
    loglevel: str = "info"
    accesslog: str | None = None
    errorlog: str = "-"
    access_log_format: str = (
        '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
    )
    logconfig_json: str | None = None

    # Internal
    env_orig: dict[str, str] = field(default_factory=lambda: os.environ.copy())

    @property
    def worker_class_str(self) -> str:
        # Auto-select based on threads
        if self.threads > 1:
            return "gthread"
        return "sync"

    @property
    def worker_class(self) -> type:
        # Auto-select based on threads
        if self.threads > 1:
            uri = "plain.server.workers.gthread.ThreadWorker"
        else:
            uri = "plain.server.workers.sync.SyncWorker"

        worker_class = util.load_class(uri)
        if hasattr(worker_class, "setup"):
            worker_class.setup()  # type: ignore[call-non-callable]  # hasattr check doesn't narrow type
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
