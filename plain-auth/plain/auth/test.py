from __future__ import annotations

from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, Any

from plain.http import Response
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
    assert session.session_key is not None, "Session key should exist after save()"

    # Build the same Set-Cookie a real response would send, matching
    # plain.sessions' SessionMiddleware, then copy it onto the test client.
    response = Response()
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session.session_key,
        domain=settings.SESSION_COOKIE_DOMAIN,
        path=settings.SESSION_COOKIE_PATH,
        secure=bool(settings.SESSION_COOKIE_SECURE),
        httponly=bool(settings.SESSION_COOKIE_HTTPONLY),
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )
    client.cookies.update(response.cookies)


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
