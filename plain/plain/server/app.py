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
    """
    Plain's server application.

    This class provides the interface for running the WSGI server.
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg: Config = cfg
        self.callable: Any = None

    def load(self) -> Any:
        """Load the WSGI application."""
        # Import locally to avoid circular dependencies and allow
        # the WSGI module to handle Plain runtime setup
        from plain.wsgi import app

        return app

    def wsgi(self) -> Any:
        """Get the WSGI application."""
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
