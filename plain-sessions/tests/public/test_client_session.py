"""Reading and writing a test client's session from the test."""

from plain.runtime import settings
from plain.sessions.testing import get_client_session
from plain.testing import Client


def test_a_client_without_a_session_gets_one_and_its_cookie() -> None:
    client = Client()
    assert settings.SESSION_COOKIE_NAME not in client.cookies

    session = get_client_session(client)

    assert client.cookies[settings.SESSION_COOKIE_NAME].value == session.session_key


def test_what_the_test_saves_is_there_the_next_time() -> None:
    client = Client()
    session = get_client_session(client)
    session["theme"] = "dark"
    session.save()

    assert get_client_session(client)["theme"] == "dark"
