"""
CLI runtime utilities.

This module provides decorators and utilities for CLI commands.
"""

from collections.abc import Callable

_running_command: str | None = None
_running_command_is_found = False
_to_do_when_it_is_found: list[Callable[[], None]] = []


def set_running_command(name: str | None) -> None:
    """
    Say which top-level command this process is running. None takes it back.

    Code that runs during `plain.runtime.setup()` behaves differently by
    command (plain.dev starts the database for `test` and not for `docs`), and
    it runs before the command does, so it can't ask the command. Whoever
    starts a command says so here first: the `plain` CLI when it dispatches
    one, and an entry point that can be started without the CLI, such as
    `python -m plain.test`, for itself.

    A name is only what was typed. Whether there is such a command is said
    afterwards, with `the_running_command_was_found()`.
    """
    global _running_command, _running_command_is_found
    _running_command = name
    _running_command_is_found = False
    _to_do_when_it_is_found.clear()


def get_running_command() -> str | None:
    """The command `set_running_command` was given, or None if nobody said."""
    return _running_command


def the_running_command_was_found() -> None:
    """
    Say that the command `set_running_command` named is a command.

    The `plain` CLI can't tell a command a package or the app registers from
    one that was mistyped until the app has loaded, so `plain.runtime.setup()`
    runs for both. What should only happen for a command that exists waits
    for this: see `when_the_running_command_is_found`.
    """
    global _running_command_is_found
    _running_command_is_found = True

    waiting = list(_to_do_when_it_is_found)
    _to_do_when_it_is_found.clear()
    for do in waiting:
        do()


def running_command_is_found() -> bool:
    """Whether the command that was named has been found to be one."""
    return _running_command_is_found


def when_the_running_command_is_found(do: Callable[[], None]) -> None:
    """
    Call `do` once the running command is known to exist, and never if it
    turns out not to.

    For what a setup hook starts on a command's behalf and nothing stops
    afterwards: background services, a container. `plain tset` runs the hook
    too, and has nothing that needs them.

    In a process nobody named a command for (a script that calls `setup()`),
    there is nothing to wait for, and `do` is called now.
    """
    if _running_command is None or _running_command_is_found:
        do()
        return
    _to_do_when_it_is_found.append(do)


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
