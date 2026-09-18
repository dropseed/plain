"""End-to-end tests for the session lifecycle across HTTP requests.

These exercise the promise a session makes to a user: data written on one
request is readable on the next, expired sessions are discarded, and
flushing clears both the stored data and the session row.
"""

from datetime import timedelta

from plain.runtime import settings
from plain.sessions.models import Session
from plain.test import Client
from plain.utils import timezone

SESSION_COOKIE = settings.SESSION_COOKIE_NAME


def test_data_persists_across_requests(db):
    client = Client()

    client.get("/set?value=hello")
    response = client.get("/get")

    assert response.status_code == 200
    assert response.content == b"hello"


def test_separate_clients_have_separate_sessions(db):
    first = Client()
    second = Client()

    first.get("/set?value=one")

    # A brand-new client shares nothing with the first.
    assert second.get("/get").content == b"<none>"
    assert first.get("/get").content == b"one"


def test_session_cookie_is_reused(db):
    client = Client()

    client.get("/set?value=x")
    key_after_set = client.cookies[SESSION_COOKIE].value

    client.get("/get")

    # Reading an existing session shouldn't rotate the key; the client keeps
    # sending the same cookie.
    assert client.cookies[SESSION_COOKIE].value == key_after_set
    assert Session.query.filter(session_key=key_after_set).exists()


def test_expired_session_is_not_loaded(db):
    client = Client()
    client.get("/set?value=stale")

    # Force the stored session to be expired.
    Session.query.update(expires_at=timezone.now() - timedelta(seconds=1))

    assert client.get("/get").content == b"<none>"


def test_flush_clears_data_and_deletes_row(db):
    client = Client()
    client.get("/set?value=temp")
    assert Session.query.count() == 1

    response = client.post("/flush")
    assert response.status_code == 200

    # The flushed row is deleted, and a later read (which writes nothing)
    # creates no replacement.
    assert Session.query.count() == 0
    assert client.get("/get").content == b"<none>"
    assert Session.query.count() == 0
