from __future__ import annotations

from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from .exceptions import SessionNotAvailable

if TYPE_CHECKING:
    from plain.http import Request

    from .core import SessionStore

_request_sessions: WeakKeyDictionary[Request, SessionStore] = WeakKeyDictionary()


def set_request_session(request: Request, session: SessionStore) -> None:
    """Store the session for this request."""
    _request_sessions[request] = session


def get_request_session(request: Request) -> SessionStore:
    """
    Get the session for this request.

    Raises SessionNotAvailable if no session is set (typically because
    SessionMiddleware hasn't been called yet or an error occurred before it could run).
    """
    try:
        return _request_sessions[request]
    except KeyError as e:
        raise SessionNotAvailable(
            "Session is not available for this request. "
            "Ensure SessionMiddleware is installed and has been called."
        ) from e
