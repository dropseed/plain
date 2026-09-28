"""What the test client's response is: a fixed set of names that describe
what was sent, and nothing borrowed from the response the view returned."""

from plain.http import Request, Response
from plain.test import Client, RequestFactory
from plain.test.client import ClientResponse


def test_the_names_a_response_has() -> None:
    response = Client().get("/")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/html")
    assert response.body == b"Hello, world!"
    assert response.text == "Hello, world!"
    assert response.redirect_to is None
    assert response.redirect_chain == []
    assert response.exception is None
    assert response.streaming is False
    assert list(response.cookies) == []


def test_request_is_the_request_that_was_sent() -> None:
    response = Client().get("/", query_params={"page": "2"})

    assert isinstance(response.request, Request)
    assert response.request.method == "GET"
    assert response.request.query_params["page"] == "2"


def test_resolver_match_is_the_route_the_path_resolves_to() -> None:
    response = Client().get("/")

    assert response.resolver_match is not None
    assert response.resolver_match.url_name == "index"


def test_resolver_match_is_none_for_a_path_with_no_route() -> None:
    response = Client().get("/no-such-route")

    assert response.status_code == 404
    assert response.resolver_match is None


def test_returned_response_is_the_response_object_itself() -> None:
    response = Client().get("/")

    assert type(response.returned_response) is Response
    assert not isinstance(response, Response)


def test_every_documented_name_is_a_property() -> None:
    for name in ClientResponse._NAMES:
        assert isinstance(getattr(ClientResponse, name), property)


def test_any_method_can_be_sent() -> None:
    response = Client().request(method="POST", path="/echo-body", body=b"12345")

    assert response.text == "5"
    assert response.request.method == "POST"


def test_request_factory_request_takes_the_clients_keywords() -> None:
    request = RequestFactory().request(
        method="PUT",
        path="/things",
        query_params={"page": "2"},
        json_data={"name": "kettle"},
        headers={"X-Trace": "abc"},
    )

    assert request.method == "PUT"
    assert request.query_params["page"] == "2"
    assert request.json_data == {"name": "kettle"}
    assert request.headers["Content-Type"] == "application/json"
    assert request.headers["X-Trace"] == "abc"
