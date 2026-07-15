from __future__ import annotations

import subprocess
import sys
from unittest import mock

from click.testing import CliRunner

from plain.cli.shell import shell


def _invoke(args):
    """Invoke the shell command with subprocess.run stubbed out.

    Returns the list of (cmd, kwargs) passed to subprocess.run so tests can
    assert which execution path was taken without spawning a real interpreter.
    """
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    with mock.patch("plain.cli.shell.subprocess.run", side_effect=fake_run):
        result = CliRunner().invoke(shell, args, prog_name="plain")

    assert result.exit_code == 0, result.output
    return calls


def _child_body(calls):
    """The generated `python -c <body>` string for a non-interactive path."""
    (cmd, _kwargs) = calls[0]
    assert cmd[:2] == [sys.executable, "-c"]
    return cmd[2]


def test_dash_c_executes_string():
    body = _child_body(_invoke(["-c", "print(1)"]))
    assert "plain.runtime.setup()" in body
    assert "exec(compile('print(1)'" in body
    assert "sys.argv = ['-c']" in body
    # User code runs in a fresh namespace, not the wrapper's globals.
    assert "{'__name__': '__main__'}" in body


def test_piped_stdin_runs_setup():
    # Regression guard (#66): piped input must run plain.runtime.setup()
    # explicitly, since PYTHONSTARTUP is skipped for non-interactive stdin.
    # CliRunner provides a non-tty stdin.
    body = _child_body(_invoke([]))
    assert "plain.runtime.setup()" in body
    assert "sys.stdin.read()" in body
    assert "sys.argv = ['-']" in body


def test_tty_launches_enriched_repl():
    # On a tty, `shell` opens the enriched REPL. Enrichment (banner +
    # SHELL_IMPORT) is delivered via PYTHONSTARTUP, which only the interactive
    # interpreter honors — so no `-c` payload, and Plain's startup file must
    # win over any PYTHONSTARTUP the user has exported.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    fake_stdin = mock.Mock()
    fake_stdin.isatty.return_value = True
    assert shell.callback is not None
    with (
        mock.patch("plain.cli.shell.subprocess.run", side_effect=fake_run),
        mock.patch("plain.cli.shell.sys.stdin", fake_stdin),
        mock.patch.dict("os.environ", {"PYTHONSTARTUP": "/home/user/.pythonrc"}),
    ):
        shell.callback(interface=None, command=None)

    (cmd, kwargs) = calls[0]
    assert cmd[0] == sys.executable
    assert kwargs["env"]["PYTHONSTARTUP"].endswith("startup.py")
    assert "-c" not in cmd
