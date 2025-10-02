from __future__ import annotations

from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from plain.http import Request

_request_users: WeakKeyDictionary[Request, Any | None] = WeakKeyDictionary()


def set_request_user(request: Request, user: Any | None) -> None:
    """Store the authenticated user for this request."""
    _request_users[request] = user


def get_request_user(request: Request) -> Any | None:
    """
    Get the authenticated user for this request, if any.

    Lazily loads the user from the session on first access.
    """
    if request not in _request_users:
        from .sessions import get_user

        user = get_user(request)

        # Don't need to store a bunch of None values
        if not user:
            return None

        _request_users[request] = user

    return _request_users[request]
