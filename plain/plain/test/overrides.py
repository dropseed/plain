"""
Context managers for temporarily changing runtime state in tests.

Scope is visible as indentation — state changes enter through `with` blocks,
never through injection.
"""

import inspect
from collections.abc import Generator, MutableMapping
from contextlib import contextmanager
from typing import Any

from .exceptions import require_app

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

    require_app("override_settings")

    # Snapshot every original value before applying anything, so an unknown
    # setting name raises without leaving earlier overrides applied. The
    # apply loop runs inside the try so a rejected value (settings are
    # type-checked on assignment) still restores whatever was applied.
    original = {name: getattr(settings, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(settings, name, value)
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
        # Raises AttributeError for a name the target doesn't have.
        original = getattr(target, name)
        if inspect.isclass(target):
            # Restore what the class itself held, not what attribute lookup
            # found. Lookup unwraps a staticmethod or classmethod, and finds
            # attributes the class only inherits — putting that value back
            # would leave a plain function, or a copy of the inherited
            # attribute, on the class.
            original = vars(target).get(name, _MISSING)
        setattr(target, name, value)
        try:
            yield
        finally:
            if original is _MISSING:
                delattr(target, name)
            else:
                setattr(target, name, original)
