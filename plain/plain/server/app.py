#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

from __future__ import annotations

import sys
from typing import Any

from . import util
from .arbiter import Arbiter


class ServerApplication:
    """Plain's server application."""

    def __init__(
        self,
        *,
        bind: list[str],
        workers: int,
        threads: int,
        timeout: int,
        max_requests: int,
        reload: bool,
        pidfile: str | None,
        certfile: str | None,
        keyfile: str | None,
        accesslog: bool,
    ) -> None:
        self.bind = bind
        self.workers = workers
        self.threads = threads
        self.timeout = timeout
        self.max_requests = max_requests
        self.reload = reload
        self.pidfile = pidfile
        self.certfile = certfile
        self.keyfile = keyfile
        self.accesslog = accesslog

    @property
    def address(self) -> list[tuple[str, int] | str]:
        return [util.parse_address(util.bytes_to_str(bind)) for bind in self.bind]

    @property
    def is_ssl(self) -> bool:
        return self.certfile is not None or self.keyfile is not None

    def load(self) -> Any:
        """Load the request handler."""
        from plain.internal.handlers.base import BaseHandler

        handler = BaseHandler()
        handler.load_middleware()
        return handler

    def run(self) -> None:
        """Run the server."""

        try:
            Arbiter(self).run()
        except RuntimeError as e:
            print(f"\nError: {e}\n", file=sys.stderr)
            sys.stderr.flush()
            sys.exit(1)
