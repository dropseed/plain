#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

import plain.runtime

SERVER = "plain"
SERVER_SOFTWARE = f"{SERVER}/{plain.runtime.__version__}"

# Import public API from core module
from .core import PlainServerApp, run_server

__all__ = ["run_server", "PlainServerApp", "SERVER_SOFTWARE"]
