from __future__ import annotations

from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from plain.http import Request

_request_impersonators: WeakKeyDictionary[Request, Any] = WeakKeyDictionary()


def set_request_impersonator(request: Request, impersonator: Any) -> None:
    """Store the impersonator (original user) for this request."""
    _request_impersonators[request] = impersonator


def get_request_impersonator(request: Request) -> Any | None:
    """Get the impersonator (original user) for this request, if any."""
    return _request_impersonators.get(request)
