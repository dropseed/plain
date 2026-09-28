"""Logging a test client in and out without going through a login view."""

from app.users.models import User
from plain.auth.requests import get_request_user
from plain.auth.test import login_client, logout_client
from plain.sessions.test import get_client_session
from plain.test import Client


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
