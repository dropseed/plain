#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

import sys

from .arbiter import Arbiter
from .config import Config


class BaseApplication:
    """
    An application interface for configuring and loading
    the various necessities for any given web framework.
    """

    def __init__(self, usage=None, prog=None):
        self.usage = usage
        self.cfg = None
        self.callable = None
        self.prog = prog
        self.logger = None
        self.do_load_config()

    def do_load_config(self):
        """
        Loads the configuration
        """
        try:
            self.load_default_config()
            self.load_config()
        except Exception as e:
            print(f"\nError: {str(e)}", file=sys.stderr)
            sys.stderr.flush()
            sys.exit(1)

    def load_default_config(self):
        # init configuration
        self.cfg = Config(self.usage, prog=self.prog)

    def init(self, parser, opts, args):
        raise NotImplementedError

    def load(self):
        raise NotImplementedError

    def load_config(self):
        """
        This method is used to load the configuration from one or several input(s).
        Custom Command line, configuration file.
        You have to override this method in your class.
        """
        raise NotImplementedError

    def reload(self):
        self.do_load_config()

    def wsgi(self):
        if self.callable is None:
            self.callable = self.load()
        return self.callable

    def run(self):
        try:
            Arbiter(self).run()
        except RuntimeError as e:
            print(f"\nError: {e}\n", file=sys.stderr)
            sys.stderr.flush()
            sys.exit(1)


class Application(BaseApplication):
    # 'init' and 'load' methods are implemented by WSGIApplication.
    # pylint: disable=abstract-method

    def run(self):
        if self.cfg.print_config:
            print(self.cfg)

        if self.cfg.print_config or self.cfg.check_config:
            try:
                self.load()
            except Exception:
                msg = "\nError while loading the application:\n"
                print(msg, file=sys.stderr)
                sys.stderr.flush()
                sys.exit(1)
            sys.exit(0)

        super().run()
