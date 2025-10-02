from __future__ import annotations

from typing import Any

from plain.runtime import settings

from .core import SessionStore


def get_client_session(client: Any) -> SessionStore:
    """Return the current session variables for a test client."""
    cookie = client.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie:
        return SessionStore(cookie.value)
    session = SessionStore()
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    return session
