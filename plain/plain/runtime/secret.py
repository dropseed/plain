from __future__ import annotations

from typing import Annotated


class _SecretMarker:
    """Runtime marker for secret settings. Used as Annotated metadata."""

    pass


type Secret[T] = Annotated[T, _SecretMarker()]
"""
Marker type for sensitive settings. Values are masked in output/logs.

Usage:
    SECRET_KEY: Secret[str]
    DATABASE_PASSWORD: Secret[str]

At runtime, the value is still a plain str - this is purely for
indicating that the setting should be masked when displayed.

Secret[str] is a type alias for Annotated[str, _SecretMarker()],
so type checkers see it as just str.
"""
