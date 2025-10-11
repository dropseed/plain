#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

# Supported workers
SUPPORTED_WORKERS = {
    "sync": "plain.server.workers.sync.SyncWorker",
    "gthread": "plain.server.workers.gthread.ThreadWorker",
}
