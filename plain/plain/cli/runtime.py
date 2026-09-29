"""
CLI runtime utilities.

This module provides decorators and utilities for CLI commands.
"""

from collections.abc import Callable

_running_command: str | None = None


def set_running_command(name: str | None) -> None:
    """
    Say which top-level command this process is running. None takes it back.

    Code that runs during `plain.runtime.setup()` behaves differently by
    command (plain.dev starts the database for `test` and not for `docs`), and
    it runs before the command does, so it can't ask the command. Whoever
    starts a command says so here first: the `plain` CLI when it dispatches
    one, and an entry point that can be started without the CLI, such as
    `python -m plain.test`, for itself.
    """
    global _running_command
    _running_command = name


def get_running_command() -> str | None:
    """The command `set_running_command` was given, or None if nobody said."""
    return _running_command


def without_runtime_setup[F: Callable](f: F) -> F:
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
    f.without_runtime_setup = True  # ty: ignore[unresolved-attribute] (dynamic attribute for decorator)
    return f


def common_command[F: Callable](f: F) -> F:
    """
    Decorator to mark commands as commonly used.

    Common commands are shown in a separate "Common Commands" section
    in the help output, making them easier to discover.

    Example:
        @common_command
        @click.command()
        def dev(**options):
            ...
    """
    f.is_common_command = True  # ty: ignore[unresolved-attribute] (dynamic attribute for decorator)
    return f
