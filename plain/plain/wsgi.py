import plain.runtime
from plain.internal.handlers.wsgi import WSGIHandler


def _get_wsgi_application():
    plain.runtime.setup()
    return WSGIHandler()


# The default `plain.wsgi:app` WSGI application
app = _get_wsgi_application()
