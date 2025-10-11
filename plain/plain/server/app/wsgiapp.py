#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

import os

from plain.server.app.base import Application

from ..errors import ConfigError
from . import util


class WSGIApplication(Application):
    def init(self, parser, opts, args):
        self.app_uri = None

        if opts.paste:
            from .pasterapp import has_logging_config

            config_uri = os.path.abspath(opts.paste)
            config_file = config_uri.split('#')[0]

            if not os.path.exists(config_file):
                raise ConfigError("%r not found" % config_file)

            self.cfg.set("default_proc_name", config_file)
            self.app_uri = config_uri

            if has_logging_config(config_file):
                self.cfg.set("logconfig", config_file)

            return

        if len(args) > 0:
            self.cfg.set("default_proc_name", args[0])
            self.app_uri = args[0]

    def load_config(self):
        super().load_config()

        if self.app_uri is None:
            if self.cfg.wsgi_app is not None:
                self.app_uri = self.cfg.wsgi_app
            else:
                raise ConfigError("No application module specified.")

    def load_wsgiapp(self):
        return util.import_app(self.app_uri)

    def load_pasteapp(self):
        from .pasterapp import get_wsgi_app
        return get_wsgi_app(self.app_uri, defaults=self.cfg.paste_global_conf)

    def load(self):
        if self.cfg.paste is not None:
            return self.load_pasteapp()
        else:
            return self.load_wsgiapp()


def run(prog=None):
    """\
    The ``gunicorn`` command line runner for launching Gunicorn with
    generic WSGI applications.
    """
    from plain.server.app.wsgiapp import WSGIApplication
    WSGIApplication("%(prog)s [OPTIONS] [APP_MODULE]", prog=prog).run()


if __name__ == '__main__':
    run()
