from __future__ import annotations

import os
import subprocess
import sys
import traceback
import types

import click

from plain.cli.runtime import common_command

_STARTUP = os.path.join(os.path.dirname(__file__), "startup.py")


def _run_source(source: str, filename: str, argv0: str) -> None:
    """Execute one-off code in this process, as the `__main__` module.

    The CLI has already run plain.runtime.setup() before any command executes,
    so the app is configured. Registering a real module as
    sys.modules["__main__"] keeps `python -c` semantics: user code gets a
    clean namespace, and objects it defines can be resolved through their
    module (pickle).
    """
    sys.argv = [argv0]
    module = types.ModuleType("__main__")
    sys.modules["__main__"] = module
    try:
        exec(compile(source, filename, "exec"), module.__dict__)
    except Exception as e:
        # Drop this function's frame so the traceback starts at the user's
        # code, like `python -c`.
        e.__traceback__ = e.__traceback__.tb_next if e.__traceback__ else None
        traceback.print_exception(e)
        sys.exit(1)


# Each interface runs under the same interpreter (`sys.executable`) that the
# CLI itself uses, so the REPL sees the project's installed packages.
_INTERFACES = {
    "ipython": [sys.executable, "-m", "IPython"],
    "bpython": [sys.executable, "-m", "bpython"],
    "python": [sys.executable],
}


def _run_repl(interface: str | None) -> None:
    """Enriched interactive REPL: banner + SHELL_IMPORT via PYTHONSTARTUP."""
    if interface is None:
        try:
            import IPython  # noqa: F401  # ty: ignore[unresolved-import]

            interface = "ipython"
        except ImportError:
            interface = "python"
    # Plain's startup file must win over any PYTHONSTARTUP the user has exported,
    # otherwise the banner + SHELL_IMPORT enrichment is silently replaced.
    result = subprocess.run(
        _INTERFACES[interface],
        env={**os.environ, "PYTHONSTARTUP": _STARTUP},
    )
    if result.returncode:
        sys.exit(result.returncode)


@common_command
@click.command()
@click.option(
    "-i",
    "--interface",
    type=click.Choice(list(_INTERFACES)),
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
        _run_source(command, "<string>", argv0="-c")
    elif not sys.stdin.isatty():
        # Piped input can't go through the REPL — PYTHONSTARTUP (and thus the
        # enrichment) is only honored for interactive sessions.
        _run_source(sys.stdin.read(), "<stdin>", argv0="-")
    else:
        _run_repl(interface)
