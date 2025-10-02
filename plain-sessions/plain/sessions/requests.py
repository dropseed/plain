from __future__ import annotations

from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from plain.http import Request

    from .core import SessionStore

_request_sessions: WeakKeyDictionary[Request, SessionStore] = WeakKeyDictionary()


def set_request_session(request: Request, session: SessionStore) -> None:
    """Store the session for this request."""
    _request_sessions[request] = session


def get_request_session(request: Request) -> SessionStore:
    """Get the session for this request. Raises KeyError if no session is set."""
    return _request_sessions[request]
