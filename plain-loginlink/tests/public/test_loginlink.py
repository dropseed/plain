"""Behavior regression baseline — plain.loginlink passwordless auth.

Drives the request-a-link and follow-a-link flows end-to-end through
``plain.test.Client``. Assertions cover only browser-observable outcomes —
HTTP status, redirect targets, login state (probed via the login-gated
``/whoami`` view), rendered failure pages, and sent email.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.users.models import User

from plain.email.test import outbox
from plain.loginlink.links import generate_link_url
from plain.test import Client, RequestFactory


def is_logged_in(client: Client) -> bool:
    """Whether the client's current session authenticates the /whoami view."""
    return client.get("/whoami").status_code == 200


def token_path(message) -> str:
    """The /loginlink/token/... path carried by a captured login-link email."""
    match = re.search(r"/loginlink/token/[^\s\"'<>]+", message.body)
    assert match, "login link email should contain a token URL"
    return match.group(0)


class TestRequestLink:
    def test_request_page_renders(self):
        response = Client().get("/login")

        assert response.status_code == 200
        assert 'name="email"' in response.content.decode()

    def test_known_email_sends_link(self):
        User.query.create(email="known@example.com")
        client = Client()

        response = client.post(
            "/login", form_data={"email": "known@example.com", "next": ""}
        )

        assert response.status_code == 302
        assert response.url == "/loginlink/sent"
        assert len(outbox) == 1
        assert outbox[0].to == ["known@example.com"]

    def test_unknown_email_sends_nothing_without_leaking(self):
        client = Client()

        response = client.post(
            "/login", form_data={"email": "ghost@example.com", "next": ""}
        )

        # Identical 302 -> /loginlink/sent as the known case: no existence leak.
        assert response.status_code == 302
        assert response.url == "/loginlink/sent"
        assert len(outbox) == 0


class TestAlreadyLoggedIn:
    def test_login_page_redirects_home(self):
        client = Client()
        client.force_login(User.query.create(email="repeat@example.com"))

        response = client.get("/login")

        assert response.status_code == 302
        assert response.url == "/"

    def test_login_page_redirects_to_next(self):
        client = Client()
        client.force_login(User.query.create(email="repeat@example.com"))

        response = client.get("/login?next=/whoami")

        assert response.status_code == 302
        assert response.url == "/whoami"

    def test_empty_next_redirects_home(self):
        client = Client()
        client.force_login(User.query.create(email="repeat@example.com"))

        response = client.get("/login?next=")

        # An empty Location header would redirect the browser back to
        # the login page in a loop.
        assert response.status_code == 302
        assert response.url == "/"

    def test_external_next_redirects_home(self):
        client = Client()
        client.force_login(User.query.create(email="repeat@example.com"))

        response = client.get("/login?next=https://evil.com")

        assert response.status_code == 302
        assert response.url == "/"


class TestFollowLink:
    def test_valid_link_logs_in(self):
        User.query.create(email="follow@example.com")
        client = Client()
        client.post("/login", form_data={"email": "follow@example.com", "next": ""})
        assert len(outbox) == 1

        response = client.get(token_path(outbox[0]))

        assert response.status_code == 302
        assert is_logged_in(client)

    def test_invalid_link_shows_failure_page(self):
        client = Client()

        response = client.get(
            "/loginlink/token/not-a-real-token", follow_redirects=True
        )

        assert response.status_code == 200
        assert "Link Invalid" in response.content.decode()
        assert not is_logged_in(client)

    def test_expired_link_shows_failure_page(self):
        user = User.query.create(email="expired@example.com")
        # Mint an already-expired link with the package's public helper.
        url = generate_link_url(
            request=RequestFactory().get("/"),
            user=user,
            email=user.email,
            expires_in=-3600,
        )

        response = Client().get(urlsplit(url).path, follow_redirects=True)

        assert response.status_code == 200
        assert "Link Expired" in response.content.decode()
