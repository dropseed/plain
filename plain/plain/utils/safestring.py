"""
Functions for working with "safe strings": strings that can be displayed safely
without further escaping in HTML. Marking something as a "safe string" means
that the producer of the string has already turned characters that should not
be interpreted by the HTML engine (e.g. '<') into the appropriate entities.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from plain.utils.functional import keep_lazy

_T = TypeVar("_T")


class SafeData:
    __slots__ = ()

    def __html__(self) -> SafeData:
        """
        Return the html representation of a string for interoperability.

        This allows other template engines to understand Plain's SafeData.
        """
        return self


class SafeString(str, SafeData):
    """
    A str subclass that has been specifically marked as "safe" for HTML output
    purposes.
    """

    __slots__ = ()

    def __add__(self, rhs: str) -> SafeString | str:  # type: ignore[override]
        """
        Concatenating a safe string with another safe bytestring or
        safe string is safe. Otherwise, the result is no longer safe.
        """
        t = super().__add__(rhs)
        if isinstance(rhs, SafeData):
            return SafeString(t)
        return t

    def __str__(self) -> str:
        return self


def _safety_decorator(
    safety_marker: Callable[[Any], _T], func: Callable[..., Any]
) -> Callable[..., _T]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> _T:
        return safety_marker(func(*args, **kwargs))

    return wrapper


@keep_lazy(SafeString)
def mark_safe(s: Any) -> SafeString | SafeData | Callable[..., Any]:
    """
    Explicitly mark a string as safe for (HTML) output purposes. The returned
    object can be used everywhere a string is appropriate.

    If used on a method as a decorator, mark the returned data as safe.

    Can be called multiple times on a single string.
    """
    if hasattr(s, "__html__"):
        return s
    if callable(s):
        return _safety_decorator(mark_safe, s)
    return SafeString(s)
