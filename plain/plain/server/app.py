#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

from __future__ import annotations

import argparse
import sys
from typing import Any

from .arbiter import Arbiter
from .config import Config


class BaseApplication:
    """
    An application interface for configuring and loading
    the various necessities for any given web framework.
    """

    def __init__(self, usage: str | None = None, prog: str | None = None) -> None:
        self.usage: str | None = usage
        self.cfg: Config | None = None
        self.callable: Any = None
        self.prog: str | None = prog
        self.logger: Any = None
        self.do_load_config()

    def do_load_config(self) -> None:
        """
        Loads the configuration
        """
        try:
            self.load_config()
        except Exception as e:
            print(f"\nError: {str(e)}", file=sys.stderr)
            sys.stderr.flush()
            sys.exit(1)

    def init(
        self, parser: argparse.ArgumentParser, opts: argparse.Namespace, args: list[str]
    ) -> None:
        raise NotImplementedError

    def load(self) -> Any:
        raise NotImplementedError

    def load_config(self) -> None:
        """
        This method is used to load the configuration from one or several input(s).
        Custom Command line, configuration file.
        You have to override this method in your class.
        """
        raise NotImplementedError

    def reload(self) -> None:
        self.do_load_config()

    def wsgi(self) -> Any:
        if self.callable is None:
            self.callable = self.load()
        return self.callable

    def run(self) -> None:
        try:
            Arbiter(self).run()
        except RuntimeError as e:
            print(f"\nError: {e}\n", file=sys.stderr)
            sys.stderr.flush()
            sys.exit(1)
