from __future__ import annotations

from typing import Any


def is_iterable(x: Any) -> bool:
    "An implementation independent way of checking for iterables"
    try:
        iter(x)
    except TypeError:
        return False
    else:
        return True
