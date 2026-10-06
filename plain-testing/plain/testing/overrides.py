"""
Context managers for temporarily changing runtime state in tests.

Scope is visible as indentation — state changes enter through `with` blocks,
never through injection.
"""

from collections.abc import Generator, Mapping, MutableMapping
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
    duration of the block.

        with patch(billing, "charge_card", fake_charge):
            checkout(cart)

        with patch(os.environ, "PLAIN_DEBUG", "true"):
            ...

    When the block ends, the target holds what it held before. For an
    attribute, what a target holds is what is in its own `__dict__`, which
    isn't always what reading the attribute finds:

    - A class that only inherits the attribute holds nothing, so the patch is
      deleted and the class inherits again. So does an instance whose method
      was patched.
    - A class holds a `staticmethod` or `classmethod` object, so that is what
      goes back, not the function that reading it returns.

    Two kinds of target keep their values somewhere else, and get back the
    value that was read before the block:

    - A mapping. Its keys are patched, and a key that wasn't there is removed.
    - An attribute the target doesn't store in its `__dict__`: a property or
      a slot, or any attribute of an object that handles setting itself, as
      `plain.runtime.settings` does.
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
        return

    # Raises AttributeError for a name the target doesn't have.
    read_before = getattr(target, name)
    held_before = _held_by(target).get(name, _MISSING)

    setattr(target, name, value)
    # Where that went says where the original has to go back to.
    stored_by_the_target = name in _held_by(
        target
    ) and not _is_set_through_a_descriptor(target, name)

    try:
        yield
    finally:
        if not stored_by_the_target:
            setattr(target, name, read_before)
        elif held_before is _MISSING:
            delattr(target, name)
        else:
            setattr(target, name, held_before)


def _held_by(target: Any) -> Mapping[str, Any]:
    """What a target holds itself: its `__dict__`, or nothing if it has none."""
    try:
        return vars(target)
    except TypeError:
        # No `__dict__`: an instance of a class that declares `__slots__`.
        return {}


def _is_set_through_a_descriptor(target: Any, name: str) -> bool:
    """
    Whether setting this attribute is taken over by the target's type: a
    property, a slot, or anything else that defines `__set__`.
    """
    for klass in type(target).__mro__:
        if name in vars(klass):
            return hasattr(type(vars(klass)[name]), "__set__")
    return False
