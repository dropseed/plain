from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class Secret(Generic[T]):
    """
    Marker type for sensitive settings. Values are masked in output/logs.

    Usage:
        SECRET_KEY: Secret[str]
        DATABASE_PASSWORD: Secret[str]

    At runtime, the value is still a plain str - this is purely for
    indicating that the setting should be masked when displayed.
    """

    pass
