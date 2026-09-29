"""What the test client's response is: a fixed set of names that describe
what was sent, and nothing borrowed from the response the view returned."""

import inspect
from functools import cached_property

from plain.http import Request, Response
from plain.test import Client, build_request, case, cases, raises
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


# What a test client is usually expected to have, and doesn't here. Each one
# says what to write.


@cases(
    case("force_login", "login_client(client, user)", id="force_login"),
    case("logout", "logout_client(client)", id="logout"),
    case("session", "get_client_session(client)", id="session"),
    case("trace", 'client.request("TRACE", path)', id="trace"),
)
def test_a_name_the_client_used_to_have_says_what_to_write(name, replacement) -> None:
    with raises(AttributeError, match="The test client has no") as caught:
        getattr(Client(), name)

    assert replacement in str(caught.exception)


def test_any_other_name_the_client_lacks_says_what_it_has() -> None:
    with raises(AttributeError, match="It makes requests") as caught:
        Client().no_such_thing  # noqa: B018

    assert "`websocket`" in str(caught.exception)
    assert "`cookies`" in str(caught.exception)


@cases("post", "put", "patch", "delete")
def test_data_passed_by_position_says_which_keyword(verb) -> None:
    send = getattr(Client(), verb)

    with raises(TypeError, match="keywords after it") as caught:
        send("/", {"email": "a@example.com"})

    assert "`form_data=`" in str(caught.exception)
    assert "`json_data=`" in str(caught.exception)


@cases("get", "head", "options")
def test_a_query_passed_by_position_says_which_keyword(verb) -> None:
    send = getattr(Client(), verb)

    with raises(TypeError, match="keywords after it") as caught:
        send("/", {"page": "2"})

    assert "`query_params=`" in str(caught.exception)


def test_the_verbs_keep_the_signatures_they_are_written_with() -> None:
    parameters = list(inspect.signature(Client.post).parameters)

    assert parameters[:2] == ["self", "path"]
    assert "form_data" in parameters
    assert "json_data" in parameters
    assert "args" not in parameters


def test_a_client_prints_as_what_it_is_without_its_cookies_values() -> None:
    client = Client()
    client.cookies["sessionid"] = "a-secret-session-key"

    assert repr(client) == "<Client cookies=['sessionid']>"
