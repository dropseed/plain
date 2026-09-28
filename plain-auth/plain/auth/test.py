from typing import TYPE_CHECKING, Any

from plain.http.request import Request
from plain.runtime import settings
from plain.sessions import SessionStore
from plain.sessions.requests import get_request_session, set_request_session
from plain.sessions.test import get_client_session

from .requests import set_request_user
from .sessions import get_user, login, logout

if TYPE_CHECKING:
    from plain.test import Client

__all__ = ["login_client", "logout_client"]


def login_client(client: Client, user: Any) -> None:
    """Log a user into a test client, without going through a login view.

    Writes the session cookie to `client.cookies`, so every request the
    client makes afterwards is that user's.
    """
    request = Request(method="GET", path="/")
    session = get_client_session(client)
    if not session:
        session = SessionStore()
    set_request_session(request, session)
    login(request, user)
    session = get_request_session(request)
    session.save()
    assert session.session_key is not None
    session_cookie = settings.SESSION_COOKIE_NAME
    client.cookies[session_cookie] = session.session_key
    cookie_data: dict[str, Any] = {
        "max-age": None,
        "path": "/",
        "domain": settings.SESSION_COOKIE_DOMAIN,
        "secure": settings.SESSION_COOKIE_SECURE or None,
        "expires": None,
    }
    # Morsel.update() is typed for str-only values, but these cookie
    # attributes are legitimately None (unset). Set them one at a time
    # through __setitem__, which is typed for Any and keeps Morsel's own
    # reserved-key validation (unlike bypassing update() with dict.update()).
    morsel = client.cookies[session_cookie]
    for key, value in cookie_data.items():
        morsel[key] = value


def logout_client(client: Client) -> None:
    """Log a test client out: end its session and drop its cookies."""
    request = Request(method="GET", path="/")
    session = get_client_session(client)
    if session:
        set_request_session(request, session)
        user = get_user(request)
        set_request_user(request, user)
    else:
        session = SessionStore()
        set_request_session(request, session)
    logout(request)
    client.cookies.clear()
