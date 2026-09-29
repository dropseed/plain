import sys
from pathlib import Path

from plain.cli.runtime import get_running_command


def has_pyproject_toml(target_path: str | Path) -> bool:
    return (Path(target_path) / "pyproject.toml").exists()


def running_command() -> str | None:
    """
    The top-level `plain` command this process is running. None for a bare
    `plain` or `plain --help`.

    Whoever started the command says which it is: the `plain` CLI when it
    dispatches one, and `python -m plain.testing` for itself, where the arguments
    name test targets and not a command. A process nobody told (a server
    worker, a script that calls `setup()`) is read from its arguments.

    Only the top-level command, so `plain docs testing` isn't taken for
    `plain test`.
    """
    told = get_running_command()
    if told is not None:
        return told

    arguments = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not arguments:
        return None
    return arguments[0]
