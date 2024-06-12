import bolt.runtime
from bolt.internal.handlers.wsgi import WSGIHandler


def get_wsgi_application():
    """
    The public interface to Bolt's WSGI support. Return a WSGI callable.

    Avoids making bolt.internal.handlers.WSGIHandler a public API, in case the
    internal WSGI implementation changes or moves in the future.
    """
    bolt.runtime.setup()
    return WSGIHandler()


app = get_wsgi_application()
