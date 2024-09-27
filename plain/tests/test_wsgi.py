from io import BytesIO


def test_wsgi_app():
    """
    Test the default plain.wsgi.app import and
    basic behavior with minimal environ input.
    """
    # Import this here because just importing triggers setup()
    # which is usually fine in wsgi usage but not what we want related to our other tests
    from plain.wsgi import app

    response = app(
        {
            "REQUEST_METHOD": "GET",
            "wsgi.input": BytesIO(b""),
            "wsgi.url_scheme": "https",
        },
        lambda *args: None,
    )

    assert response.status_code == 200
    assert response.content == b"Hello, world!"
