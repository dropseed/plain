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
    assert session.session_key is not None, "session.save() always assigns a key"
    session_cookie = settings.SESSION_COOKIE_NAME
    client.cookies[session_cookie] = session.session_key
    cookie_data = {
        "max-age": None,
        "path": "/",
        "domain": settings.SESSION_COOKIE_DOMAIN,
        "secure": settings.SESSION_COOKIE_SECURE or None,
        "expires": None,
    }
    # Morsel is a plain dict at runtime and accepts these attribute values
    # (some legitimately None/bool), but typeshed's override of update()
    # only declares the str-value case.
    client.cookies[session_cookie].update(cookie_data)  # ty: ignore[invalid-argument-type]


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
