from typing import TYPE_CHECKING

from plain.runtime import settings

from .core import SessionStore

if TYPE_CHECKING:
    from plain.testing import Client

__all__ = ["get_client_session"]


def get_client_session(client: Client) -> SessionStore:
    """The session a test client's cookie points to.

    A client that has no session yet gets a new one, and its cookie.
    """
    cookie = client.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie:
        return SessionStore(cookie.value)
    session = SessionStore()
    session.save()
    assert session.session_key is not None
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    return session
