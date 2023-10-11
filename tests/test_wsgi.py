from io import BytesIO

from bolt.wsgi import app


def test_wsgi_app():
    """
    Test the default bolt.wsgi.app import and
    basic behavior with minimal environ input.
    """
    response = app(
        {
            "REQUEST_METHOD": "GET",
            "wsgi.input": BytesIO(b""),
        },
        lambda *args: None,
    )

    assert response.status_code == 200
    assert response.content == b"Hello, world!"
