"""
The `plain test` command end to end: a project on disk, run in its own
process, judged by what it prints and how it exits.
"""

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    exit_code: int
    output: str


def run_in_project(files: dict[str, str], *arguments: str) -> CommandResult:
    root = Path(tempfile.mkdtemp())
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)

    completed = subprocess.run(
        [sys.executable, "-m", "plain.testing", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        exit_code=completed.returncode,
        output=completed.stdout + completed.stderr,
    )


PRINTING_LIFECYCLE = (
    "from contextlib import contextmanager\n"
    "\n"
    "from plain.test import TestLifecycle\n"
    "\n"
    "\n"
    "class AppTestLifecycle(TestLifecycle):\n"
    "    @contextmanager\n"
    "    def around_test(self, test):\n"
    "        print(f'protecting {test.id}')\n"
    "        try:\n"
    "            yield\n"
    "        finally:\n"
    "            print(f'released {test.id}')\n"
)


def test_the_app_lifecycle_wraps_tests_it_was_never_mentioned_in():
    result = run_in_project(
        {
            "tests/lifecycle.py": PRINTING_LIFECYCLE,
            "tests/test_one.py": "def test_one():\n    print('test body')\n",
        }
    )
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines.index("protecting tests/test_one.py::test_one") < lines.index(
        "test body"
    )
    assert lines.index("test body") < lines.index(
        "released tests/test_one.py::test_one"
    )


def test_a_broken_app_lifecycle_stops_the_run_before_any_test():
    result = run_in_project(
        {
            "tests/lifecycle.py": "class AppTestLifecycle:\n    pass\n",
            "tests/test_one.py": "def test_one():\n    print('test body')\n",
        }
    )
    assert result.exit_code == 2
    assert "doesn't define a TestLifecycle subclass" in result.output
    assert "test body" not in result.output
    assert "passed" not in result.output


def test_a_test_that_asks_for_fixtures_is_told_what_to_do():
    result = run_in_project(
        {
            "tests/test_signup.py": (
                "def test_signup(db, client):\n"
                "    assert True\n"
                "\n"
                "def test_fine():\n"
                "    assert True\n"
            ),
            "tests/test_other.py": "def test_ok():\n    assert True\n",
        }
    )
    assert result.exit_code == 1
    assert "COLLECTION ERROR" in result.output
    assert "test_signup(db, client) takes parameters" in result.output
    assert "There are no fixtures" in result.output
    # Nothing ran far enough to fail with a TypeError of its own.
    assert "missing 2 required positional arguments" not in result.output
    assert "1 passed, 1 collection errors" in result.output


SKIPPING_TESTS = (
    "from plain.test import skip, skip_test\n"
    "\n"
    "def test_runs():\n"
    "    assert True\n"
    "\n"
    "def test_decides_for_itself():\n"
    "    skip_test('No bucket reachable from here')\n"
    "\n"
    "@skip('Waiting on the billing API')\n"
    "def test_declared():\n"
    "    assert False\n"
)


def test_skips_are_counted_and_say_why():
    result = run_in_project({"tests/test_skips.py": SKIPPING_TESTS})
    assert result.exit_code == 0
    assert "1 passed, 2 skipped" in result.output
    assert (
        "SKIPPED tests/test_skips.py::test_decides_for_itself "
        "(No bucket reachable from here)"
    ) in result.output
    assert (
        "SKIPPED tests/test_skips.py::test_declared (Waiting on the billing API)"
    ) in result.output


def test_verbose_skips_say_why_on_their_own_line():
    result = run_in_project({"tests/test_skips.py": SKIPPING_TESTS}, "-v")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert (
        "SKIPPED tests/test_skips.py::test_decides_for_itself "
        "(No bucket reachable from here)"
    ) in lines
    # Said once, on the test's own line, not again in a list at the end.
    assert result.output.count("test_decides_for_itself") == 1
