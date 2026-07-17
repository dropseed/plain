"""
Context managers for temporarily changing runtime state in tests.

Scope is visible as indentation — state changes enter through `with` blocks,
never through injection.
"""

from __future__ import annotations

from collections.abc import Generator, MutableMapping
from contextlib import contextmanager
from typing import Any

__all__ = ["override_settings", "patch"]

_MISSING = object()


@contextmanager
def override_settings(**overrides: Any) -> Generator[Any]:
    """
    Set Plain settings for the duration of the block, restoring the
    originals on exit.

        with override_settings(DEBUG=True):
            ...
    """
    from plain.runtime import settings

    # Snapshot every original value before applying anything, so an unknown
    # setting name raises without leaving earlier overrides applied.
    original = {name: getattr(settings, name) for name in overrides}
    for name, value in overrides.items():
        setattr(settings, name, value)
    try:
        yield settings
    finally:
        for name, value in original.items():
            setattr(settings, name, value)


@contextmanager
def patch(target: Any, name: str, value: Any) -> Generator[None]:
    """
    Replace an attribute (or a mapping key, e.g. os.environ) for the
    duration of the block, restoring the original on exit.

        with patch(billing, "charge_card", fake_charge):
            checkout(cart)

        with patch(os.environ, "PLAIN_DEBUG", "true"):
            ...
    """
    if isinstance(target, MutableMapping):
        original = target.get(name, _MISSING)
        target[name] = value
        try:
            yield
        finally:
            if original is _MISSING:
                target.pop(name, None)
            else:
                target[name] = original
    else:
        original = getattr(target, name)
        setattr(target, name, value)
        try:
            yield
        finally:
            setattr(target, name, original)
