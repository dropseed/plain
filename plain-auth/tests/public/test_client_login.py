"""Logging a test client in and out without going through a login view."""

from app.users.models import User
from plain.auth.requests import get_request_user
from plain.auth.test import login_client, logout_client
from plain.postgres.test import capture_queries
from plain.sessions.models import Session
from plain.sessions.test import get_client_session
from plain.testing import Client


def test_login_client_makes_every_request_the_users() -> None:
    user = User.query.create(username="ada")
    client = Client()

    login_client(client, user)

    assert get_request_user(client.get("/").request) == user
    assert get_request_user(client.get("/").request) == user


def test_logout_client_makes_the_client_anonymous() -> None:
    user = User.query.create(username="ada")
    client = Client()
    login_client(client, user)

    logout_client(client)

    assert list(client.cookies) == []
    assert get_request_user(client.get("/").request) is None


def test_login_client_keeps_what_the_session_already_held() -> None:
    user = User.query.create(username="ada")
    client = Client()
    session = get_client_session(client)
    session["cart"] = "3 items"
    session.save()

    login_client(client, user)

    assert get_client_session(client)["cart"] == "3 items"


def test_a_first_login_leaves_one_session_behind() -> None:
    user = User.query.create(username="ada")
    client = Client()

    login_client(client, user)

    # The session the client got a cookie for is the one the login used.
    [session] = Session.query.all()
    assert client.cookies["sessionid"].value == session.session_key


def test_logging_out_a_client_that_never_logged_in_leaves_no_session() -> None:
    client = Client()

    logout_client(client)

    assert list(client.cookies) == []
    assert Session.query.count() == 0


def writes_to_the_session_table(queries) -> list[str]:
    """The first word of each statement that changes a session row."""
    statements = queries.sql_statements(table="plainsessions_session")
    return [
        statement.split()[0]
        for statement in statements
        if statement.startswith(("INSERT", "UPDATE", "DELETE"))
    ]


def test_a_first_login_writes_no_session_it_then_replaces() -> None:
    user = User.query.create(username="ada")
    client = Client()

    with capture_queries() as queries:
        login_client(client, user)

    # The session is made under the key the login gives it, and saved with
    # the user in it. No earlier session is written first and then removed.
    assert writes_to_the_session_table(queries) == ["INSERT", "INSERT"]
    assert len(queries.sql_statements()) == 7


def test_a_login_by_a_client_that_has_a_session_changes_its_key() -> None:
    user = User.query.create(username="ada")
    client = Client()
    get_client_session(client)

    with capture_queries() as queries:
        login_client(client, user)

    # Under a new key, with the old one removed, and saved.
    assert writes_to_the_session_table(queries) == ["INSERT", "DELETE", "INSERT"]


def test_logging_out_a_client_that_never_logged_in_writes_nothing() -> None:
    client = Client()

    with capture_queries() as queries:
        logout_client(client)

    assert writes_to_the_session_table(queries) == []
