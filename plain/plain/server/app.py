#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from .arbiter import Arbiter

if TYPE_CHECKING:
    from .config import Config


class ServerApplication:
    """Plain's server application."""

    def __init__(self, cfg: Config) -> None:
        self.cfg: Config = cfg
        self.callable: Any = None

    def load(self) -> Any:
        """Load the request handler."""
        import plain.runtime
        from plain.internal.handlers.wsgi import WSGIHandler

        plain.runtime.setup()
        return WSGIHandler()

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
