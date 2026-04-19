from plain.test import Client


def test_unknown_method_is_not_allowed():
    """Non-standard HTTP methods must not invoke arbitrary view attributes.

    Previously `getattr(self, method.lower())` with no whitelist meant a
    request with method `GET_RESPONSE` would recursively call
    `View.get_response`, blowing the stack.
    """
    client = Client()

    for method in ("GET_RESPONSE", "GET_REQUEST_HANDLER", "_ALLOWED_METHODS"):
        request = client._request_factory.generic(method, "/")
        response = client.request(request)
        assert response.status_code == 405, (
            f"method={method} returned {response.status_code}"
        )


def test_standard_methods_still_dispatch():
    client = Client()
    assert client.get("/").status_code == 200
