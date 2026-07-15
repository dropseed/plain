from __future__ import annotations

import subprocess
import sys
from unittest import mock

from click.testing import CliRunner

from plain.cli.python import python, shell


def _invoke(command, args):
    """Invoke a CLI command with subprocess.run stubbed out.

    Returns the list of (cmd, kwargs) passed to subprocess.run so tests can
    assert which execution path the dispatcher took without spawning a real
    interpreter.
    """
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    with mock.patch("plain.cli.python.subprocess.run", side_effect=fake_run):
        result = CliRunner().invoke(command, args, prog_name="plain")

    assert result.exit_code == 0, result.output
    return calls


def _child_body(calls):
    """The generated `python -c <body>` string for a non-interactive path."""
    (cmd, _kwargs) = calls[0]
    assert cmd[:2] == [sys.executable, "-c"]
    return cmd[2]


def test_dash_c_executes_string():
    body = _child_body(_invoke(python, ["-c", "print(1)"]))
    assert "plain.runtime.setup()" in body
    assert "exec(compile('print(1)'" in body
    assert "sys.argv = ['-c']" in body
    # User code runs in a fresh namespace, not the wrapper's globals.
    assert "{'__name__': '__main__'}" in body


def test_dash_c_forwards_trailing_args():
    # `python -c CMD a b` → sys.argv = ['-c', 'a', 'b']; the first positional
    # must not be swallowed by the `script` argument.
    body = _child_body(_invoke(python, ["-c", "print(1)", "a", "b"]))
    assert "sys.argv = ['-c', 'a', 'b']" in body


def test_dash_c_forwards_option_shaped_args():
    # Everything after the -c payload passes through verbatim, even tokens
    # that look like plain's own options — matching the interpreter.
    body = _child_body(
        _invoke(python, ["-c", "print(1)", "--interface", "python", "-c", "x"])
    )
    assert "sys.argv = ['-c', '--interface', 'python', '-c', 'x']" in body
    assert "exec(compile('print(1)'" in body


def test_dash_m_runs_module_as_main():
    body = _child_body(_invoke(python, ["-m", "app.tasks", "a", "b"]))
    assert "plain.runtime.setup()" in body
    assert "runpy.run_module('app.tasks', run_name='__main__', alter_sys=True)" in body
    assert "sys.argv = ['app.tasks', 'a', 'b']" in body


def test_file_runs_as_main_with_args(tmp_path):
    script = tmp_path / "script.py"
    script.write_text("print(1)")
    body = _child_body(_invoke(python, [str(script), "a", "b"]))
    assert "plain.runtime.setup()" in body
    assert f"runpy.run_path({str(script)!r}, run_name='__main__')" in body
    assert f"sys.argv = [{str(script)!r}, 'a', 'b']" in body
    # The script's directory goes on sys.path, like `python script.py`.
    assert f"sys.path.insert(0, {str(tmp_path)!r})" in body


def test_file_not_found_is_clean_error():
    result = CliRunner().invoke(python, ["missing.py"], prog_name="plain")
    assert result.exit_code == 2
    assert "can't open file" in result.output


def test_script_args_colliding_with_options_pass_through(tmp_path):
    # `plain python script.py -c foo` must forward `-c foo` to the script as
    # sys.argv, not treat `-c` as plain's own option.
    script = tmp_path / "script.py"
    script.write_text("print(1)")
    body = _child_body(_invoke(python, [str(script), "-c", "foo"]))
    assert f"sys.argv = [{str(script)!r}, '-c', 'foo']" in body


def test_dash_reads_stdin():
    body = _child_body(_invoke(python, ["-"]))
    assert "sys.stdin.read()" in body
    assert "sys.argv = ['-']" in body


def test_no_args_non_tty_reads_stdin():
    # CliRunner provides a non-tty stdin, so bare `plain python` execs stdin
    # rather than opening a REPL.
    body = _child_body(_invoke(python, []))
    assert "sys.stdin.read()" in body


def test_unknown_option_is_an_error():
    result = CliRunner().invoke(python, ["-x"], prog_name="plain")
    assert result.exit_code != 0
    assert "Unknown option" in result.output


def test_help_option():
    result = CliRunner().invoke(python, ["--help"], prog_name="plain")
    assert result.exit_code == 0
    assert "plain python -m module" in result.output


def test_shell_tty_launches_enriched_repl():
    # On a tty, `shell` opens the enriched REPL. Enrichment (banner +
    # SHELL_IMPORT) is delivered via PYTHONSTARTUP, which only the interactive
    # interpreter honors — so no `-c` payload.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    fake_stdin = mock.Mock()
    fake_stdin.isatty.return_value = True
    assert shell.callback is not None
    with (
        mock.patch("plain.cli.python.subprocess.run", side_effect=fake_run),
        mock.patch("plain.cli.python.sys.stdin", fake_stdin),
    ):
        shell.callback(interface=None)

    (cmd, kwargs) = calls[0]
    assert kwargs["env"]["PYTHONSTARTUP"].endswith("startup.py")
    assert "-c" not in cmd


def test_shell_piped_stdin_runs_setup():
    # Regression guard (#66): piped input into `shell` must run
    # plain.runtime.setup() explicitly, since PYTHONSTARTUP is skipped for
    # non-interactive stdin. CliRunner provides a non-tty stdin.
    body = _child_body(_invoke(shell, []))
    assert "plain.runtime.setup()" in body
    assert "sys.stdin.read()" in body
