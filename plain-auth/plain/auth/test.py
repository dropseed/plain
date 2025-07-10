from http.cookies import SimpleCookie

from plain.http.request import HttpRequest
from plain.runtime import settings
from plain.sessions import SessionStore

from .sessions import get_user, login, logout


def login_client(client, user):
    """Log a user into a test client."""
    request = HttpRequest()
    if client.session:
        request.session = client.session
    else:
        request.session = SessionStore()
    login(request, user)
    request.session.save()
    session_cookie = settings.SESSION_COOKIE_NAME
    client.cookies[session_cookie] = request.session.session_key
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
    request = HttpRequest()
    if client.session:
        request.session = client.session
        request.user = get_user(request)
    else:
        request.session = SessionStore()
    logout(request)
    client.cookies = SimpleCookie()
