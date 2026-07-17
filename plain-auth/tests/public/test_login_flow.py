"""End-to-end tests for the real ``login()`` / ``logout()`` session flow.

These exercise the functions users actually call from their login views —
covering session persistence across requests, session-fixation protection,
logout, and safe user-switching — rather than the test-only ``force_login``
shortcut.
"""

from app.users.models import User

from plain.runtime import settings
from plain.test import Client

SESSION_COOKIE = settings.SESSION_COOKIE_NAME


def _session_cookie(client):
    morsel = client.cookies.get(SESSION_COOKIE)
    return morsel.value if morsel else None


def test_login_persists_across_requests():
    user = User.query.create(username="alice")
    client = Client()

    # A protected page is unreachable before logging in.
    assert client.get("/whoami").status_code == 302

    resp = client.post("/session-login", form_data={"user_id": user.id})
    assert resp.status_code == 200

    # The same client is now recognized on a later, separate request.
    resp = client.get("/whoami")
    assert resp.status_code == 200
    assert resp.content == b"alice"


def test_login_rotates_session_key():
    """Logging in from an anonymous session issues a new session key
    (session-fixation protection)."""
    user = User.query.create(username="bob")
    client = Client()

    # Establish an anonymous session (with data) so a cookie already exists.
    client.get("/visit")
    anon_key = _session_cookie(client)
    assert anon_key is not None

    client.post("/session-login", form_data={"user_id": user.id})
    logged_in_key = _session_cookie(client)

    assert logged_in_key is not None
    assert logged_in_key != anon_key


def test_logout_flushes_session():
    user = User.query.create(username="carol")
    client = Client()

    client.post("/session-login", form_data={"user_id": user.id})
    assert client.get("/whoami").status_code == 200

    resp = client.post("/session-logout")
    assert resp.status_code == 200

    # After logout the protected page redirects to login again.
    assert client.get("/whoami").status_code == 302


def test_login_as_different_user_replaces_session():
    """Logging in as a second user must not retain the first user's session."""
    first = User.query.create(username="first")
    second = User.query.create(username="second")
    client = Client()

    client.post("/session-login", form_data={"user_id": first.id})
    assert client.get("/whoami").content == b"first"

    client.post("/session-login", form_data={"user_id": second.id})
    assert client.get("/whoami").content == b"second"
