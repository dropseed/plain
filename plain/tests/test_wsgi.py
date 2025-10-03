from io import BytesIO

from plain.http import Response
from plain.internal.handlers.wsgi import WSGIHandler


def test_wsgi_handler():
    """
    Test the default plain.wsgi.app import and
    basic behavior with minimal environ input.
    """
    wsgi = WSGIHandler()
    response = wsgi(
        {
            "REQUEST_METHOD": "GET",
            "wsgi.input": BytesIO(b""),
            "wsgi.url_scheme": "https",
        },
        lambda *args: None,
    )

    assert isinstance(response, Response)
    assert response.status_code == 200
    assert response.content == b"Hello, world!"
