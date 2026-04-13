from __future__ import annotations

from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes import enduser_attributes

if TYPE_CHECKING:
    from app.users.models import User

    from plain.http import Request

_request_users: WeakKeyDictionary[Request, User | None] = WeakKeyDictionary()


def _stamp_span(user: User | None) -> None:
    if user is None:
        return
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute(enduser_attributes.ENDUSER_ID, str(user.id))


def set_request_user(request: Request, user: User | None) -> None:
    """Store the authenticated user for this request."""
    _request_users[request] = user
    _stamp_span(user)


def get_request_user(request: Request) -> User | None:
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
        _stamp_span(user)

    return _request_users[request]
