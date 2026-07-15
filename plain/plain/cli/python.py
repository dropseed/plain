from __future__ import annotations

import os
import subprocess
import sys

import click

from plain.cli.runtime import common_command

# Runs in the child interpreter before any user code, so the app is fully
# configured (settings, packages, etc.) for the -c, -m, file, and stdin modes.
_SETUP = "import plain.runtime; plain.runtime.setup()"

_STARTUP = os.path.join(os.path.dirname(__file__), "startup.py")

# User code executes in a fresh namespace so the wrapper's own imports
# (plain.runtime, sys) don't leak into it — matching `python -c`/stdin.
_FRESH_GLOBALS = "{'__name__': '__main__'}"


def _exit_with(result: subprocess.CompletedProcess) -> None:
    if result.returncode:
        sys.exit(result.returncode)


def _run_child(body: str, *, argv: list[str]) -> None:
    """Run setup + `body` in a child interpreter with sys.argv set to `argv`.

    The child inherits our stdin, so `plain python -` and piped input work.
    """
    code = f"import sys; sys.argv = {argv!r}; {_SETUP}; {body}"
    _exit_with(subprocess.run([sys.executable, "-c", code]))


def _run_command(command: str, args: list[str]) -> None:
    """`plain python -c "..."` — execute a string, then exit."""
    _run_child(
        f"exec(compile({command!r}, '<string>', 'exec'), {_FRESH_GLOBALS})",
        argv=["-c", *args],
    )


def _run_module(module: str, args: list[str]) -> None:
    """`plain python -m module` — run a module as __main__."""
    # alter_sys=True makes runpy point sys.argv[0] at the module's own file,
    # matching `python -m`.
    _run_child(
        f"import runpy; runpy.run_module({module!r}, run_name='__main__', alter_sys=True)",
        argv=[module, *args],
    )


def _run_file(script: str, args: list[str]) -> None:
    """`plain python script.py` — run a file as __main__."""
    if not os.path.exists(script):
        click.echo(
            f"plain python: can't open file {script!r}: No such file or directory",
            err=True,
        )
        sys.exit(2)
    # `python script.py` puts the script's directory at sys.path[0]. We prepend
    # it rather than replace, keeping the cwd on the path for app imports.
    script_dir = os.path.dirname(os.path.abspath(script))
    _run_child(
        f"sys.path.insert(0, {script_dir!r}); "
        f"import runpy; runpy.run_path({script!r}, run_name='__main__')",
        argv=[script, *args],
    )


def _run_stdin(args: list[str]) -> None:
    """`plain python -` or piped input — execute stdin, then exit."""
    _run_child(
        f"exec(compile(sys.stdin.read(), '<stdin>', 'exec'), {_FRESH_GLOBALS})",
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


@common_command
@click.command(
    add_help_option=False,
    context_settings={"ignore_unknown_options": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def python(ctx: click.Context, args: tuple[str, ...]) -> None:
    """Run Python with the app configured.

    Supports the common execution modes of the `python` interpreter, always
    running `plain.runtime.setup()` first:

    \b
      plain python              # interactive REPL (banner + SHELL_IMPORT)
      plain python -c "..."     # execute a string, then exit
      plain python -m module    # run a module as __main__
      plain python script.py    # run a file as __main__
      plain python -            # execute stdin, then exit

    Use -i/--interface to pick the REPL (ipython, bpython, python).
    """
    # Hand-parse the leading flags the way the interpreter does: the first
    # token that names a payload (-c, -m, a file, or -) ends our parsing, and
    # everything after it passes through untouched as the child's sys.argv.
    # Click's own option parser can't do that — it keeps matching
    # option-shaped tokens after the payload.
    argv = list(args)
    interface: str | None = None
    while argv:
        arg = argv[0]
        if arg in ("-h", "--help"):
            click.echo(ctx.get_help())
            return
        if arg in ("-i", "--interface") or arg.startswith("--interface="):
            if "=" in arg:
                interface = arg.split("=", 1)[1]
                argv = argv[1:]
            else:
                if len(argv) < 2:
                    ctx.fail(f"Argument expected for the {arg} option")
                interface = argv[1]
                argv = argv[2:]
            if interface not in _INTERFACES:
                ctx.fail(
                    f"Invalid interface {interface!r} (choose from {', '.join(_INTERFACES)})"
                )
            continue
        if arg == "-c":
            if len(argv) < 2:
                ctx.fail("Argument expected for the -c option")
            _run_command(argv[1], argv[2:])
            return
        if arg == "-m":
            if len(argv) < 2:
                ctx.fail("Argument expected for the -m option")
            _run_module(argv[1], argv[2:])
            return
        if arg == "-":
            _run_stdin(argv[1:])
            return
        if arg.startswith("-"):
            ctx.fail(f"Unknown option: {arg}")
        _run_file(arg, argv[1:])
        return
    _repl_or_stdin(interface)


@click.command()
@click.option(
    "-i",
    "--interface",
    type=click.Choice(["ipython", "bpython", "python"]),
    help="Specify an interactive interpreter interface.",
)
def shell(interface: str | None) -> None:
    """Interactive Python shell with your app's objects preloaded.

    Alias for the interactive REPL from `plain python`. Use `plain python`
    directly for -c, -m, file, and stdin execution.
    """
    _repl_or_stdin(interface)
