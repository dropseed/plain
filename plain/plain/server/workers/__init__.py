#
#
# This file is part of gunicorn released under the MIT license.
# See the LICENSE for more information.
#
# Vendored and modified for Plain.

# supported gunicorn workers.
SUPPORTED_WORKERS = {
    "sync": "plain.server.workers.sync.SyncWorker",
    "eventlet": "plain.server.workers.geventlet.EventletWorker",
    "gevent": "plain.server.workers.ggevent.GeventWorker",
    "gevent_wsgi": "plain.server.workers.ggevent.GeventPyWSGIWorker",
    "gevent_pywsgi": "plain.server.workers.ggevent.GeventPyWSGIWorker",
    "tornado": "plain.server.workers.gtornado.TornadoWorker",
    "gthread": "plain.server.workers.gthread.ThreadWorker",
}
