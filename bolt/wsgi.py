import bolt.runtime
from bolt.handlers.wsgi import WSGIHandler


def get_wsgi_application():
    """
    The public interface to Django's WSGI support. Return a WSGI callable.

    Avoids making bolt.handlers.WSGIHandler a public API, in case the
    internal WSGI implementation changes or moves in the future.
    """
    bolt.runtime.setup()
    return WSGIHandler()


app = get_wsgi_application()
