"""
CLI runtime utilities.

This module provides decorators and utilities for CLI commands.
"""

from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F", bound=Callable)


def without_runtime_setup(f: F) -> F:
    """
    Decorator to mark commands that don't need plain.runtime.setup().

    Use this for commands that don't access settings or app code,
    particularly for commands that fork (like server) where setup()
    should happen in the worker process, not the parent.

    Example:
        @without_runtime_setup
        @click.command()
        def server(**options):
            ...
    """
    f.without_runtime_setup = True  # type: ignore[attr-defined]  # dynamic attribute for decorator
    return f
