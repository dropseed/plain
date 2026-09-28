"""What the test client's response is: a fixed set of names that describe
what was sent, and nothing borrowed from the response the view returned."""

from functools import cached_property

from plain.http import Request, Response
from plain.test import Client, build_request
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
    assert list(response.cookies) == []


def test_request_is_the_request_that_was_sent() -> None:
    response = Client().get("/", query_params={"page": "2"})

    assert isinstance(response.request, Request)
    assert response.request.method == "GET"
    assert response.request.query_params["page"] == "2"


def test_the_route_that_ran_is_on_the_request() -> None:
    response = Client().get("/")

    assert response.request.resolver_match is not None
    assert response.request.resolver_match.url_name == "index"


def test_a_path_with_no_route_has_none_on_the_request() -> None:
    response = Client().get("/no-such-route")

    assert response.status_code == 404
    assert response.request.resolver_match is None


def test_whether_the_body_was_streamed_is_on_the_returned_response() -> None:
    assert Client().get("/").returned_response.streaming is False
    assert Client().get("/stream-generator").returned_response.streaming is True


def test_returned_response_is_the_response_object_itself() -> None:
    response = Client().get("/")

    assert type(response.returned_response) is Response
    assert not isinstance(response, Response)


def test_every_documented_name_is_a_property() -> None:
    for name in ClientResponse._NAMES:
        # `json_data` parses once and keeps the result.
        assert isinstance(getattr(ClientResponse, name), property | cached_property)


def test_the_documented_names_are_all_the_names() -> None:
    defined = {
        name
        for name, value in vars(ClientResponse).items()
        if isinstance(value, property | cached_property)
    }

    assert defined == set(ClientResponse._NAMES)


def test_any_method_can_be_sent() -> None:
    response = Client().request(method="POST", path="/echo-body", body=b"12345")

    assert response.text == "5"
    assert response.request.method == "POST"


def test_build_request_takes_the_clients_keywords() -> None:
    request = build_request(
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
