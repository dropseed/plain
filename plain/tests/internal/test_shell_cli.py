from __future__ import annotations

import subprocess
import sys
from unittest import mock

from click.testing import CliRunner

from plain.cli.shell import shell


def _invoke(args, input=None):
    """Invoke the shell command, restoring what one-off execution mutates.

    `-c` and stdin code run in-process as a fresh `__main__` module with
    sys.argv reset, so put both back afterward for the rest of the suite.
    """
    saved_main = sys.modules["__main__"]
    saved_argv = sys.argv
    try:
        return CliRunner().invoke(shell, args, input=input, prog_name="plain")
    finally:
        sys.modules["__main__"] = saved_main
        sys.argv = saved_argv


def test_dash_c_executes_string():
    result = _invoke(["-c", "print(1 + 1)"])
    assert result.exit_code == 0, result.output
    assert "2" in result.output


def test_dash_c_runs_in_clean_main_namespace():
    # No wrapper imports leak in, and sys.argv matches `python -c`.
    result = _invoke(["-c", "import sys; print(sys.argv, 'plain' in dir())"])
    assert result.exit_code == 0, result.output
    assert "['-c'] False" in result.output


def test_dash_c_defines_picklable_objects():
    # Classes defined in one-off code must resolve through
    # sys.modules["__main__"], like `python -c` — pickle enforces this.
    code = "import pickle\nclass A: pass\nprint(len(pickle.dumps(A())))"
    result = _invoke(["-c", code])
    assert result.exit_code == 0, result.output
    assert int(result.output.strip()) > 0


def test_dash_c_error_traceback_starts_at_user_code():
    result = _invoke(["-c", "1/0"])
    assert result.exit_code == 1
    assert 'File "<string>"' in result.output
    assert "ZeroDivisionError" in result.output
    assert "shell.py" not in result.output


def test_piped_stdin_executes():
    # Regression guard (#66): piped input must run with the app configured.
    # It executes in-process, where the CLI has already done setup.
    # CliRunner provides a non-tty stdin.
    result = _invoke([], input="import sys; print(sys.argv)")
    assert result.exit_code == 0, result.output
    assert "['-']" in result.output


def test_tty_launches_enriched_repl():
    # On a tty, `shell` opens the enriched REPL in a subprocess. Enrichment
    # (banner + SHELL_IMPORT) is delivered via PYTHONSTARTUP, which only the
    # interactive interpreter honors — and Plain's startup file must win over
    # any PYTHONSTARTUP the user has exported.
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
