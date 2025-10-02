from http.cookies import SimpleCookie

from plain.http.request import Request
from plain.runtime import settings
from plain.sessions import SessionStore
from plain.sessions.requests import get_request_session, set_request_session

from .requests import set_request_user
from .sessions import get_user, login, logout


def login_client(client, user):
    """Log a user into a test client."""
    request = Request()
    if client.session:
        session = client.session
    else:
        session = SessionStore()
    set_request_session(request, session)
    login(request, user)
    session = get_request_session(request)
    session.save()
    session_cookie = settings.SESSION_COOKIE_NAME
    client.cookies[session_cookie] = session.session_key
    cookie_data = {
        "max-age": None,
        "path": "/",
        "domain": settings.SESSION_COOKIE_DOMAIN,
        "secure": settings.SESSION_COOKIE_SECURE or None,
        "expires": None,
    }
    client.cookies[session_cookie].update(cookie_data)


def logout_client(client):
    """Log out a user from a test client."""
    request = Request()
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
