"""`python -m plain.testing` is `plain test`.

plain.dev's setup hook starts the database for a test run, and it has to
know a test run when it sees one. Started as a module, the arguments are a
module path and test targets, so a hook that read the command from them saw
a bare `plain`, or a command named after the first target.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from plain.testing import cases

PROBE = """\
from plain.dev.utils import running_command


def test_the_setup_hook_was_told_this_is_a_test_run():
    assert running_command() == "test"
"""


def run_in_a_project(command: list[str]) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        tests = Path(tmp) / "tests"
        tests.mkdir()
        (tests / "test_probe.py").write_text(PROBE)
        return subprocess.run(
            [sys.executable, "-m", *command],
            cwd=tmp,
            capture_output=True,
            text=True,
            check=False,
        )


@cases(
    ["plain", "test"],
    ["plain", "test", "tests/test_probe.py"],
    ["plain.testing"],
    ["plain.testing", "tests/test_probe.py"],
    ["coverage", "run", "-m", "plain.testing"],
    ["coverage", "run", "-m", "plain.testing", "tests/test_probe.py"],
)
def test_however_it_is_started_it_is_the_test_command(command):
    completed = run_in_a_project(command)

    assert completed.returncode == 0
    assert "1 passed" in completed.stdout
