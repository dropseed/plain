from __future__ import annotations

from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, Any

from plain.http.request import Request
from plain.runtime import settings
from plain.sessions import SessionStore
from plain.sessions.requests import get_request_session, set_request_session

from .requests import set_request_user
from .sessions import get_user, login, logout

if TYPE_CHECKING:
    from plain.test.client import Client


def login_client(client: Client, user: Any) -> None:
    """Log a user into a test client."""
    request = Request(method="GET", path="/")
    if client.session:
        session = client.session
    else:
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
    """Log out a user from a test client."""
    request = Request(method="GET", path="/")
    if client.session:
        session = client.session
        set_request_session(request, session)
        user = get_user(request)
        set_request_user(request, user)
    else:
        session = SessionStore()
        set_request_session(request, session)
    logout(request)
    client.cookies = SimpleCookie()
