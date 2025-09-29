from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def internalcode(obj: T) -> T:
    """
    A decorator that simply marks a class or function as internal.

    Do not rely on @internalcode as a developer!
    """
    return obj
