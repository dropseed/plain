#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

import plain.runtime

from .core import PlainServerApp, run_server

SERVER = "plain"
SERVER_SOFTWARE = f"{SERVER}/{plain.runtime.__version__}"

__all__ = ["run_server", "PlainServerApp", "SERVER_SOFTWARE"]
