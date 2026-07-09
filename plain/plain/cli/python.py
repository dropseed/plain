from __future__ import annotations

import os
import subprocess
import sys

import click

from plain.cli.runtime import common_command

# Runs in the child interpreter before any user code, so the app is fully
# configured (settings, packages, etc.) for the -c, file, and stdin modes.
_SETUP = "import plain.runtime; plain.runtime.setup()"

_STARTUP = os.path.join(os.path.dirname(__file__), "startup.py")


def _exit_with(result: subprocess.CompletedProcess) -> None:
    if result.returncode:
        sys.exit(result.returncode)


def _run_child(body: str, *, argv: list[str]) -> None:
    """Run setup + `body` in a child interpreter with sys.argv set to `argv`.

    The child inherits our stdin, so `plain python -` and piped input work.
    """
    code = f"{_SETUP}; import sys; sys.argv = {argv!r}; {body}"
    _exit_with(subprocess.run([sys.executable, "-c", code]))


def _run_command(command: str, args: list[str]) -> None:
    """`plain python -c "..."` — execute a string, then exit."""
    _run_child(
        f"exec(compile({command!r}, '<string>', 'exec'))",
        argv=["-c", *args],
    )


def _run_file(script: str, args: list[str]) -> None:
    """`plain python script.py` — run a file as __main__."""
    _run_child(
        f"import runpy; runpy.run_path({script!r}, run_name='__main__')",
        argv=[script, *args],
    )


def _run_stdin(args: list[str]) -> None:
    """`plain python -` or piped input — execute stdin, then exit."""
    _run_child(
        "exec(compile(sys.stdin.read(), '<stdin>', 'exec'))",
        argv=["-", *args],
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


def _repl_or_stdin(interface: str | None) -> None:
    """Interactive REPL on a tty, else execute piped stdin — both app-configured.

    Piped input can't go through the REPL: PYTHONSTARTUP (and thus the app
    setup + enrichment) is only honored interactively, so non-tty stdin must
    run through `_run_stdin`, which sets the app up explicitly.
    """
    if sys.stdin.isatty():
        _run_repl(interface)
    else:
        _run_stdin([])


_INTERFACE_OPTION = click.option(
    "-i",
    "--interface",
    type=click.Choice(["ipython", "bpython", "python"]),
    help="Specify an interactive interpreter interface.",
)


@common_command
@click.command(
    context_settings={"ignore_unknown_options": True, "allow_interspersed_args": False}
)
@_INTERFACE_OPTION
@click.option(
    "-c",
    "--command",
    help="Program passed in as a string, then exit.",
)
@click.argument("args", nargs=-1)
def python(
    interface: str | None,
    command: str | None,
    args: tuple[str, ...],
) -> None:
    """Run Python with the app configured.

    Behaves like the `python` interpreter, but always runs
    `plain.runtime.setup()` first:

      plain python              # interactive REPL (banner + SHELL_IMPORT)
      plain python -c "..."     # execute a string, then exit
      plain python script.py    # run a file as __main__
      plain python -            # execute stdin, then exit
    """
    # `args` is a flat positional vector, like the interpreter's own argv:
    # the first element names the file (or `-` for stdin), the rest pass through.
    if command is not None:
        _run_command(command, list(args))
    elif args and args[0] == "-":
        _run_stdin(list(args[1:]))
    elif args:
        _run_file(args[0], list(args[1:]))
    else:
        _repl_or_stdin(interface)


@click.command()
@_INTERFACE_OPTION
def shell(interface: str | None) -> None:
    """Interactive Python shell with your app's objects preloaded.

    Alias for the interactive REPL from `plain python`. Use `plain python`
    directly for -c, file, and stdin execution.
    """
    _repl_or_stdin(interface)
