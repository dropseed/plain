from __future__ import annotations

import os
import subprocess
import sys

import click

from plain.cli.runtime import common_command

# Runs in the child interpreter before any user code, so the app is fully
# configured (settings, packages, etc.) for the -c and stdin modes.
_SETUP = "import plain.runtime; plain.runtime.setup()"

_STARTUP = os.path.join(os.path.dirname(__file__), "startup.py")

# User code executes in a fresh namespace so the wrapper's own imports
# (plain.runtime, sys) don't leak into it.
_FRESH_GLOBALS = "{'__name__': '__main__'}"


def _exit_with(result: subprocess.CompletedProcess) -> None:
    if result.returncode:
        sys.exit(result.returncode)


def _run_child(body: str, *, argv: list[str]) -> None:
    """Run setup + `body` in a child interpreter with sys.argv set to `argv`.

    The child inherits our stdin, so piped input works.
    """
    code = f"import sys; sys.argv = {argv!r}; {_SETUP}; {body}"
    _exit_with(subprocess.run([sys.executable, "-c", code]))


def _run_command(command: str) -> None:
    """`plain shell -c "..."` — execute a string, then exit."""
    _run_child(
        f"exec(compile({command!r}, '<string>', 'exec'), {_FRESH_GLOBALS})",
        argv=["-c"],
    )


def _run_stdin() -> None:
    """Piped input — execute stdin, then exit."""
    _run_child(
        f"exec(compile(sys.stdin.read(), '<stdin>', 'exec'), {_FRESH_GLOBALS})",
        argv=["-"],
    )


# Each interface runs under the same interpreter (`sys.executable`) that the
# CLI itself uses, so the REPL sees the project's installed packages.
_INTERFACES = {
    "ipython": [sys.executable, "-m", "IPython"],
    "bpython": [sys.executable, "-m", "bpython"],
    "python": [sys.executable],
}


def _default_interface() -> list[str]:
    try:
        import IPython  # noqa: F401  # ty: ignore[unresolved-import]

        return _INTERFACES["ipython"]
    except ImportError:
        return _INTERFACES["python"]


def _run_repl(interface: str | None) -> None:
    """Enriched interactive REPL: banner + SHELL_IMPORT via PYTHONSTARTUP."""
    interface_list = _INTERFACES[interface] if interface else _default_interface()
    # Plain's startup file must win over any PYTHONSTARTUP the user has exported,
    # otherwise the banner + SHELL_IMPORT enrichment is silently replaced.
    _exit_with(
        subprocess.run(
            interface_list,
            env={**os.environ, "PYTHONSTARTUP": _STARTUP},
        )
    )


@common_command
@click.command()
@click.option(
    "-i",
    "--interface",
    type=click.Choice(["ipython", "bpython", "python"]),
    help="Specify an interactive interpreter interface.",
)
@click.option(
    "-c",
    "--command",
    help="Execute the given code and exit.",
)
def shell(interface: str | None, command: str | None) -> None:
    """Interactive Python shell with the app configured.

    Also runs one-off code and exits: `-c "..."` or piped stdin.
    """
    if command is not None:
        _run_command(command)
    elif not sys.stdin.isatty():
        # Piped input can't go through the REPL: PYTHONSTARTUP (and thus the
        # app setup + enrichment) is only honored interactively, so non-tty
        # stdin runs through a child that sets the app up explicitly.
        _run_stdin()
    else:
        _run_repl(interface)
