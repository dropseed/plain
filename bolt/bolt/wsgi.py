import bolt.runtime
from bolt.internal.handlers.wsgi import WSGIHandler


def _get_wsgi_application():
    bolt.runtime.setup()
    return WSGIHandler()


# The default `bolt.wsgi:app` WSGI application
app = _get_wsgi_application()
