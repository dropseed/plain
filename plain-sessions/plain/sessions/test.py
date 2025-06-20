from plain.runtime import settings

from .core import SessionStore


def get_client_session(client):
    """Return the current session variables for a test client."""
    cookie = client.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie:
        return SessionStore(cookie.value)
    session = SessionStore()
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    return session
