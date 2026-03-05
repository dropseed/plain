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
        self.callable: Any = None

    def __getstate__(self) -> dict:
        # One-way pickle for spawn: the callable (loaded request handler)
        # can't be pickled, but workers don't need it — they call
        # load() independently after setup().
        state = self.__dict__.copy()
        state["callable"] = None
        return state

    @property
    def address(self) -> list[tuple[str, int] | str]:
        return [util.parse_address(util.bytes_to_str(bind)) for bind in self.bind]

    @property
    def is_ssl(self) -> bool:
        return self.certfile is not None or self.keyfile is not None

    def load(self) -> Any:
        """Load the request handler."""
        import logging
        import sys

        import plain.runtime
        from plain.internal.handlers.base import BaseHandler
        from plain.logs.configure import create_log_formatter

        plain.runtime.setup()

        # Replace bootstrap handlers on the server logger with
        # propagation to the "plain" logger configured by setup().
        server_logger = logging.getLogger("plain.server")
        server_logger.handlers.clear()
        server_logger.propagate = True

        # Configure access logger based on the --access-log CLI flag.
        access_logger = logging.getLogger("plain.server.access")
        access_logger.setLevel(logging.INFO)
        access_logger.handlers.clear()
        access_logger.propagate = False
        if self.accesslog:
            log_handler = logging.StreamHandler(sys.stdout)
            log_handler.setFormatter(
                create_log_formatter(plain.runtime.settings.LOG_FORMAT)
            )
            access_logger.addHandler(log_handler)

        handler = BaseHandler()
        handler.load_middleware()
        return handler

    def handler(self) -> Any:
        """Get the request handler."""
        if self.callable is None:
            self.callable = self.load()
        return self.callable

    def run(self) -> None:
        """Run the server."""

        try:
            Arbiter(self).run()
        except RuntimeError as e:
            print(f"\nError: {e}\n", file=sys.stderr)
            sys.stderr.flush()
            sys.exit(1)
