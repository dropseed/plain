#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

# Nothing is imported here. `plain.server.app` holds the server itself
# (the arbiter, the workers, the reloader), and importing this package must
# not load it: `plain.server.inprocess` handles requests with none of that.
