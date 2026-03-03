from plain.test import Client


def test_handler():
    """
    Test that the handler processes a basic request and returns a response.
    """
    client = Client()
    response = client.get("/")

    assert response.status_code == 200
    assert response.content == b"Hello, world!"
