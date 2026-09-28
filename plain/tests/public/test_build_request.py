"""`build_request()` builds a `Request` without sending it, and `Client`
builds the ones it sends the same way."""

import plain.test
from plain.http import Request
from plain.test import Client, build_request, cases, raises


def test_a_path_goes_to_https_testserver():
    request = build_request("GET", "/things")

    assert isinstance(request, Request)
    assert request.method == "GET"
    assert request.path == "/things"
    assert request.scheme == "https"
    assert request.server_name == "testserver"
    assert request.server_port == "443"
    assert request.body == b""


def test_a_url_names_its_own_scheme_host_and_port():
    request = build_request("GET", "http://example.com:8080/things")

    assert request.path == "/things"
    assert request.scheme == "http"
    assert request.server_name == "example.com"
    assert request.server_port == "8080"


@cases(("http://testserver/", "80"), ("https://testserver/", "443"))
def test_a_url_without_a_port_gets_its_schemes_port(url, port):
    assert build_request("GET", url).server_port == port


def test_query_params_go_after_the_query_string_in_the_path():
    request = build_request("GET", "/search?q=kettle", query_params={"page": "2"})

    assert request.path == "/search"
    assert request.query_string == "q=kettle&page=2"
    assert request.query_params["q"] == "kettle"
    assert request.query_params["page"] == "2"


def test_headers_are_the_requests_headers():
    request = build_request("GET", "/", headers={"X-Trace": "abc"})

    assert request.headers["X-Trace"] == "abc"


def test_a_request_with_no_body_declares_no_content():
    request = build_request("GET", "/")

    assert "Content-Type" not in request.headers
    assert "Content-Length" not in request.headers


def test_request_factory_is_gone():
    assert not hasattr(plain.test, "RequestFactory")


def test_the_client_sends_what_build_request_builds():
    built = build_request(
        "POST", "/echo-body?a=1", form_data={"name": "Ada"}, headers={"X-Trace": "abc"}
    )

    sent = (
        Client()
        .post("/echo-body?a=1", form_data={"name": "Ada"}, headers={"X-Trace": "abc"})
        .request
    )

    assert sent.method == built.method
    assert sent.path == built.path
    assert sent.query_string == built.query_string
    assert dict(sent.headers) == dict(built.headers)
    assert sent.scheme == built.scheme
    assert sent.server_name == built.server_name
    assert sent.server_port == built.server_port


def test_the_clients_headers_go_under_the_requests_own():
    client = Client(headers={"X-Default": "client", "X-Overridden": "client"})

    request = client.get("/", headers={"X-Overridden": "request"}).request

    assert request.headers["X-Default"] == "client"
    assert request.headers["X-Overridden"] == "request"


def test_the_clients_cookies_are_sent():
    client = Client()
    client.cookies["flavor"] = "oatmeal"

    request = client.get("/").request

    assert request.cookies["flavor"] == "oatmeal"


def test_an_http_url_is_a_request_that_did_not_come_over_https():
    # HTTPS_REDIRECT_ENABLED is on by default, so plain http is redirected.
    response = Client().get("http://testserver/")

    assert response.request.scheme == "http"
    assert response.status_code == 301
    assert response.redirect_to == "https://testserver/"


def test_a_redirect_to_another_scheme_goes_to_that_schemes_port():
    response = Client().get("http://testserver/", follow_redirects=True)

    assert response.status_code == 200
    assert response.redirect_chain == [("https://testserver/", 301)]
    assert response.request.scheme == "https"
    assert response.request.server_name == "testserver"
    assert response.request.server_port == "443"


def test_raise_exceptions_is_the_name():
    with raises(TypeError, match="raise_request_exception"):
        Client(raise_request_exception=False)  # ty: ignore[unknown-argument]

    assert Client().raise_exceptions is True
    assert Client(raise_exceptions=False).raise_exceptions is False


@cases("get", "head", "options", "post", "put", "patch", "delete", "request")
def test_no_client_method_takes_secure(name):
    with raises(TypeError, match="secure"):
        if name == "request":
            Client().request("GET", "/", secure=False)  # ty: ignore[unknown-argument]
        else:
            getattr(Client(), name)("/", secure=False)
