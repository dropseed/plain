from __future__ import annotations

from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from plain.auth import get_user_model
    from plain.http import Request

    User = get_user_model()

_request_impersonators: WeakKeyDictionary[Request, User] = WeakKeyDictionary()


def set_request_impersonator(request: Request, impersonator: User) -> None:
    """Store the impersonator (original user) for this request."""
    _request_impersonators[request] = impersonator


def get_request_impersonator(request: Request) -> User | None:
    """Get the impersonator (original user) for this request, if any."""
    return _request_impersonators.get(request)
