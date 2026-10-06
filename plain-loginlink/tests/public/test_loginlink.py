"""Behavior regression baseline — plain.loginlink passwordless auth.

Drives the request-a-link and follow-a-link flows end-to-end through
``plain.testing.Client``. Assertions cover only browser-observable outcomes —
HTTP status, redirect targets, login state (probed via the login-gated
``/whoami`` view), rendered failure pages, and sent email.
"""

import re
from urllib.parse import urlsplit

from app.users.models import User
from plain.auth.testing import login_client
from plain.email.testing import outbox
from plain.loginlink.links import generate_link_url
from plain.testing import Client, build_request


def is_logged_in(client: Client) -> bool:
    """Whether the client's current session authenticates the /whoami view."""
    return client.get("/whoami").status_code == 200


def token_path(message) -> str:
    """The /loginlink/token/... path carried by a captured login-link email."""
    match = re.search(r"/loginlink/token/[^\s\"'<>]+", message.body)
    assert match, "login link email should contain a token URL"
    return match.group(0)


# Request link
def test_request_page_renders():
    response = Client().get("/login")

    assert response.status_code == 200
    assert 'name="email"' in response.text


def test_known_email_sends_link():
    User.query.create(email="known@example.com")
    client = Client()

    response = client.post(
        "/login", form_data={"email": "known@example.com", "next": ""}
    )

    assert response.status_code == 302
    assert response.redirect_to == "/loginlink/sent"
    assert len(outbox) == 1
    assert outbox[0].to == ["known@example.com"]


def test_unknown_email_sends_nothing_without_leaking():
    client = Client()

    response = client.post(
        "/login", form_data={"email": "ghost@example.com", "next": ""}
    )

    # Identical 302 -> /loginlink/sent as the known case: no existence leak.
    assert response.status_code == 302
    assert response.redirect_to == "/loginlink/sent"
    assert len(outbox) == 0


# Link expiration
def test_form_link_expires_in_is_honored():
    """A form's `link_expires_in` sets the window on the links it sends."""
    User.query.create(email="shortlived@example.com")
    client = Client()

    client.post(
        "/login-already-expired",
        form_data={"email": "shortlived@example.com", "next": ""},
    )

    response = client.get(token_path(outbox[0]), follow_redirects=True)

    assert "Link Expired" in response.text
    assert not is_logged_in(client)


# Already logged in
def test_already_logged_in_login_page_redirects_home():
    client = Client()
    login_client(client, User.query.create(email="repeat@example.com"))

    response = client.get("/login")

    assert response.status_code == 302
    assert response.redirect_to == "/"


def test_already_logged_in_login_page_redirects_to_next():
    client = Client()
    login_client(client, User.query.create(email="repeat@example.com"))

    response = client.get("/login?next=/whoami")

    assert response.status_code == 302
    assert response.redirect_to == "/whoami"


def test_already_logged_in_empty_next_redirects_home():
    client = Client()
    login_client(client, User.query.create(email="repeat@example.com"))

    response = client.get("/login?next=")

    # An empty Location header would redirect the browser back to
    # the login page in a loop.
    assert response.status_code == 302
    assert response.redirect_to == "/"


def test_already_logged_in_external_next_redirects_home():
    client = Client()
    login_client(client, User.query.create(email="repeat@example.com"))

    response = client.get("/login?next=https://evil.com")

    assert response.status_code == 302
    assert response.redirect_to == "/"


# Follow link
def test_valid_link_logs_in():
    User.query.create(email="follow@example.com")
    client = Client()
    client.post("/login", form_data={"email": "follow@example.com", "next": ""})
    assert len(outbox) == 1

    response = client.get(token_path(outbox[0]))

    assert response.status_code == 302
    assert is_logged_in(client)


def test_invalid_link_shows_failure_page():
    client = Client()

    response = client.get("/loginlink/token/not-a-real-token", follow_redirects=True)

    assert response.status_code == 200
    assert "Link Invalid" in response.text
    assert not is_logged_in(client)


def test_expired_link_shows_failure_page():
    user = User.query.create(email="expired@example.com")
    # Mint an already-expired link with the package's public helper.
    url = generate_link_url(
        request=build_request("GET", "/"),
        user=user,
        email=user.email,
        expires_in=-3600,
    )

    response = Client().get(urlsplit(url).path, follow_redirects=True)

    assert response.status_code == 200
    assert "Link Expired" in response.text
