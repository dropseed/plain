"""
The `plain test` command end to end: a project on disk, run in its own
process, judged by what it prints and how it exits.
"""

import os
import pty
import shutil
import subprocess
import sys

from plain.test import cases
from plain_test_helpers import make_project, run_in_project, run_pasted, run_runner

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
        },
        "--show-output",
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


def test_a_lifecycle_that_raises_is_shown_with_its_traceback():
    result = run_in_project(
        {
            "tests/lifecycle.py": (
                "from plain.test import TestLifecycle\n"
                "\n"
                "LIMIT = int('ten')\n"
                "\n"
                "class AppTestLifecycle(TestLifecycle):\n"
                "    pass\n"
            ),
            "tests/test_one.py": "def test_one():\n    print('test body')\n",
        }
    )
    assert result.exit_code == 2
    assert "tests/lifecycle.py could not be imported." in result.output
    assert 'tests/lifecycle.py", line 3, in <module>' in result.output
    assert "ValueError: invalid literal for int()" in result.output
    # The runner's own frames aren't part of what went wrong.
    assert "lifecycle_discovery.py" not in result.output
    assert "test body" not in result.output


def test_a_name_error_in_a_test_file_says_where():
    result = run_in_project(
        {
            "tests/test_broken.py": (
                "LIMIT = UNDEFINED_NAME\n\ndef test_one():\n    assert True\n"
            ),
            "tests/test_fine.py": "def test_ok():\n    assert True\n",
        }
    )
    assert result.exit_code == 1
    assert "COLLECTION ERROR" in result.output
    assert 'tests/test_broken.py", line 1, in <module>' in result.output
    assert "NameError: name 'UNDEFINED_NAME' is not defined" in result.output
    assert "1 passed, 1 collection errors" in result.output


def test_a_bare_skip_says_which_line():
    result = run_in_project(
        {
            "tests/test_bare.py": (
                "from plain.test import skip\n"
                "\n"
                "@skip\n"
                "def test_never():\n"
                "    assert True\n"
            ),
        }
    )
    assert result.exit_code == 1
    assert '  line 3: @skip requires a reason: @skip("why")' in result.output
    # The message is the whole of it: no class name, no traceback.
    assert "TestDefinitionError" not in result.output
    assert "Traceback" not in result.output


def test_the_runner_reads_no_env_files_itself():
    # Env files are plain.dev's to load, from its setup hook, and the ones
    # it loads are the ones for PLAIN_ENV. So with PLAIN_ENV set to
    # something else, `.env.test` is read by nothing, whether or not
    # plain.dev is installed where this suite runs: unless the runner reads
    # it itself.
    result = run_in_project(
        {
            ".env.test": "RUNNER_DOTENV_PROBE=loaded\n",
            "tests/test_env.py": (
                "import os\n"
                "\n"
                "def test_env():\n"
                "    assert os.environ['PLAIN_ENV'] == 'staging'\n"
                "    assert 'RUNNER_DOTENV_PROBE' not in os.environ\n"
            ),
        },
        environment={"PLAIN_ENV": "staging"},
    )
    assert result.exit_code == 0, result.output


def test_plain_env_is_test_unless_it_was_set():
    result = run_in_project(
        {
            "tests/test_env.py": (
                "import os\n"
                "\n"
                "def test_env():\n"
                "    assert os.environ['PLAIN_ENV'] == 'test'\n"
            ),
        },
        environment={"PLAIN_ENV": None},
    )
    assert result.exit_code == 0, result.output


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
    result = run_in_project({"tests/test_skips.py": SKIPPING_TESTS}, "--verbose")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert (
        "skipped tests/test_skips.py::test_decides_for_itself "
        "(No bucket reachable from here)"
    ) in lines
    # Said once, on the test's own line, not again in a list at the end.
    assert result.output.count("test_decides_for_itself") == 1


def test_help_lists_the_flags_and_the_target_syntax():
    root = make_project({"tests/test_one.py": "def test_one():\n    assert True\n"})
    completed = subprocess.run(
        [sys.executable, "-m", "plain", "test", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    for flag in (
        "--match",
        "--tag",
        "--exclude-tag",
        "--fail-fast",
        "--verbose",
        "--full-values",
        "--show-output",
    ):
        assert flag in completed.stdout
    assert "[TARGETS]..." in completed.stdout
    assert "tests/test_signup.py::test_welcome" in completed.stdout
    # The help is what was asked for. No test ran to produce it.
    assert "Collected" not in completed.stdout


@cases("-k", "-x", "-v", "-s")
def test_an_option_has_one_name_and_it_is_the_long_one(short):
    result = run_in_project(
        {"tests/test_one.py": "def test_one():\n    assert True\n"}, short
    )
    assert result.exit_code == 2
    assert f"No such option: {short}" in result.output
    assert "1 passed" not in result.output


def test_a_passing_run_prints_what_was_collected_and_what_came_of_it():
    result = run_in_project(
        {
            "tests/test_many.py": (
                "from plain.test import cases\n"
                "\n"
                "@cases(*range(200))\n"
                "def test_number(number):\n"
                "    assert number >= 0\n"
            )
        }
    )
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[:2] == ["Collected 200 tests", ""]
    assert lines[2].startswith("200 passed in ")
    assert len(lines) == 3


def run_on_a_terminal(directory, *arguments):
    """What the command writes to stdout when stdout is a terminal."""
    ours, theirs = pty.openpty()
    command = subprocess.Popen(
        [sys.executable, "-m", "plain.test", *arguments],
        cwd=directory,
        stdin=subprocess.DEVNULL,
        stdout=theirs,
        stderr=subprocess.DEVNULL,
    )
    os.close(theirs)

    # Read as it is written: what is left unread when the other end closes
    # is lost.
    written = b""
    while True:
        try:
            some = os.read(ours, 65536)
        except OSError:
            break  # the other end is closed
        if not some:
            break
        written += some
    os.close(ours)
    command.wait()
    return written.decode()


def test_a_terminal_is_shown_how_far_the_run_has_got_and_then_it_is_erased():
    project = make_project(
        {
            "tests/test_it.py": (
                "def test_one():\n    assert True\n\n"
                "def test_two():\n    assert False\n"
            )
        }
    )
    written = run_on_a_terminal(project)
    erase = "\r\x1b[K"
    assert f"{erase}1 of 2{erase}2 of 2, 1 failed{erase}" in written
    # Nothing of it is left: the report starts where the line was.
    report = written.rpartition(erase)[2]
    assert "FAILED tests/test_it.py::test_two" in report
    assert " of 2" not in report

    # One line per test is its own account of how far the run has got.
    assert erase not in run_on_a_terminal(project, "--verbose")
    # What is let through is written where the line would be.
    assert erase not in run_on_a_terminal(project, "--show-output")


CASES_WITH_AWKWARD_IDS = (
    "from plain.test import case, cases\n"
    "\n"
    "@cases(\n"
    "    case(1, id='annual plan'),\n"
    "    case(2, id='annual'),\n"
    '    case(3, id="it\'s $HOME"),\n'
    "    case(4, id='a*b?'),\n"
    "    case(5, id='x::y [z]'),\n"
    "    case(6, id='say \"hi\" `now`; ls'),\n"
    ")\n"
    "def test_price(number):\n"
    "    assert number == 0\n"
    "\n"
    # Lists, which a case can't be named for, so these are numbered.
    "@cases([7], [8])\n"
    "def test_numbered(number):\n"
    "    assert number == 0\n"
)


def shells() -> list[str]:
    # zsh refuses an unquoted `[0]` that matches no file, where sh passes it on.
    found = [shutil.which(name) for name in ("sh", "zsh")]
    return [shell for shell in found if shell is not None]


@cases(*shells())
def test_every_rerun_command_runs_its_own_test_when_pasted(shell):
    root = make_project({"tests/test_price.py": CASES_WITH_AWKWARD_IDS})
    failing_run = run_runner(root)
    assert "8 failed" in failing_run.output

    commands = [
        line.removeprefix("Re-run: ")
        for line in failing_run.output.splitlines()
        if line.startswith("Re-run: ")
    ]
    assert len(commands) == 8

    rerun_ids = []
    for command in commands:
        rerun = run_pasted(root, command, shell=shell)
        assert "Collected 1 test\n" in rerun.output
        failed_lines = [
            line for line in rerun.output.splitlines() if line.startswith("FAILED ")
        ]
        assert len(failed_lines) == 1
        rerun_ids.append(failed_lines[0].removeprefix("FAILED "))

    assert rerun_ids == [
        "tests/test_price.py::test_price[annual plan]",
        "tests/test_price.py::test_price[annual]",
        "tests/test_price.py::test_price[it's $HOME]",
        "tests/test_price.py::test_price[a*b?]",
        "tests/test_price.py::test_price[x::y [z]]",
        'tests/test_price.py::test_price[say "hi" `now`; ls]',
        "tests/test_price.py::test_numbered[0]",
        "tests/test_price.py::test_numbered[1]",
    ]


def test_a_rerun_command_with_nothing_for_a_shell_to_read_is_left_bare():
    result = run_in_project(
        {"tests/test_one.py": "def test_one():\n    assert False\n"}
    )
    assert "Re-run: plain test tests/test_one.py::test_one\n" in result.output


CONFTEST = (
    "import pytest\n"
    "\n"
    "@pytest.fixture\n"
    "def user(db):\n"
    "    return object()\n"
    "\n"
    "@pytest.fixture(autouse=True)\n"
    "def no_payments(monkeypatch):\n"
    "    pass\n"
)


def test_a_conftest_is_refused_and_says_where_its_contents_go():
    result = run_in_project(
        {
            "tests/conftest.py": CONFTEST,
            "tests/test_one.py": "def test_one():\n    assert True\n",
        }
    )
    assert result.exit_code == 1
    assert "COLLECTION ERROR" in result.output
    assert "tests/conftest.py" in result.output
    assert "conftest.py is a pytest file, and nothing reads it here" in result.output
    assert "such as tests/helpers.py" in result.output
    assert "`around_test()`, in\n    tests/lifecycle.py" in result.output
    assert "Fixtures in this file: user" in result.output
    assert "Autouse fixtures in this file: no_payments" in result.output
    # The tests that need nothing from it still run.
    assert "1 passed, 1 collection errors" in result.output


HELPERS = "def create_user():\n    return 'a user'\n"

TEST_USING_A_HELPER = (
    "from helpers import create_user\n"
    "\n"
    "def test_user():\n"
    "    assert create_user() == 'a user'\n"
)


def test_a_helper_module_is_imported_by_its_bare_name_from_the_project_root():
    root = make_project(
        {
            "tests/helpers.py": HELPERS,
            "tests/accounts/test_users.py": TEST_USING_A_HELPER,
        }
    )
    for arguments in ([], ["tests/accounts"], ["tests/accounts/test_users.py"]):
        result = run_runner(root, *arguments)
        assert "1 passed" in result.output
        assert result.exit_code == 0


def test_a_helper_module_is_imported_by_its_bare_name_from_inside_tests():
    root = make_project(
        {
            "tests/helpers.py": HELPERS,
            "tests/accounts/test_users.py": TEST_USING_A_HELPER,
        }
    )
    for arguments in ([], ["accounts"], ["accounts/test_users.py"]):
        result = run_runner(root / "tests", *arguments)
        assert "1 passed" in result.output
        assert result.exit_code == 0


def test_an_import_through_the_tests_directory_says_what_to_write():
    result = run_in_project(
        {
            "tests/helpers.py": HELPERS,
            "tests/test_users.py": (
                "from tests.helpers import create_user\n"
                "\n"
                "def test_user():\n"
                "    assert create_user() == 'a user'\n"
            ),
        }
    )
    assert result.exit_code == 1
    assert "COLLECTION ERROR" in result.output
    assert (
        "line 1: `from tests.helpers import create_user` should be "
        "`from helpers import create_user`"
    ) in result.output
    assert "tests/helpers.py is `helpers`" in result.output


def test_a_relative_import_says_what_to_write():
    result = run_in_project(
        {
            "tests/helpers.py": HELPERS,
            "tests/test_users.py": (
                "from .helpers import create_user\n"
                "\n"
                "def test_user():\n"
                "    assert create_user() == 'a user'\n"
            ),
        }
    )
    assert result.exit_code == 1
    assert (
        "line 1: `from .helpers import create_user` should be "
        "`from helpers import create_user`"
    ) in result.output
    assert "plain_tests" not in result.output


def test_a_lifecycle_under_the_wrong_name_stops_the_run():
    result = run_in_project(
        {
            "tests/lifecycles.py": PRINTING_LIFECYCLE,
            "tests/test_one.py": "def test_one():\n    print('test body')\n",
        }
    )
    assert result.exit_code == 2
    assert "tests/lifecycles.py mentions TestLifecycle" in result.output
    assert "tests/lifecycle.py\n" in result.output
    assert "test body" not in result.output


# What a project that was written for pytest is told


CONFTEST_WITH_A_KID = (
    "import pytest\n"
    "\n"
    "@pytest.fixture\n"
    "def kid(db):\n"
    "    return 'a kid'\n"
    "\n"
    "@pytest.fixture(autouse=True)\n"
    "def no_payments(monkeypatch):\n"
    "    pass\n"
)

USES_PYTEST = (
    "import pytest\n"
    "\n"
    "def test_pin(kid):\n"
    "    with pytest.raises(ValueError):\n"
    "        kid.set_pin('x')\n"
)


def test_a_project_written_for_pytest_is_told_each_thing_once():
    result = run_in_project(
        {
            "tests/conftest.py": CONFTEST_WITH_A_KID,
            "tests/test_a_pins.py": USES_PYTEST,
            "tests/test_b_pins.py": USES_PYTEST,
            "tests/test_c_views.py": "def test_view(db, kid):\n    assert True\n",
            "tests/test_d_views.py": "def test_view(kid):\n    assert True\n",
            "tests/test_e_fine.py": "def test_fine():\n    assert True\n",
        }
    )
    assert result.exit_code == 1
    assert "1 passed, 5 collection errors" in result.output

    headings = [
        line.removeprefix("COLLECTION ERROR ")
        for line in result.output.splitlines()
        if line.startswith("COLLECTION ERROR ")
    ]
    # The conftest first: it is where the fixtures were, so what it says
    # is what the rest are about.
    assert headings == [
        "tests/conftest.py",
        "tests/test_a_pins.py",
        "tests/test_b_pins.py",
        "tests/test_c_views.py",
        "tests/test_d_views.py",
    ]

    # Nothing got as far as failing on its own.
    assert "Traceback" not in result.output


def test_a_one_paragraph_definition_error_is_printed_with_no_blank_lines():
    """Every line of a run is read. A file that has only to say what is
    wrong with it, and where that was explained, takes the lines that says."""
    only_imports_pytest = "import pytest\n\n\ndef test_it():\n    pytest.skip()\n"
    result = run_in_project(
        {
            "tests/test_a.py": only_imports_pytest,
            "tests/test_b.py": only_imports_pytest,
            "tests/test_c.py": only_imports_pytest,
        }
    )

    lines = result.output.splitlines()
    second = lines.index("COLLECTION ERROR tests/test_b.py")
    third = lines.index("COLLECTION ERROR tests/test_c.py")
    # The first says what replaces pytest, in paragraphs, and is set off
    # from what follows it.
    assert lines[second - 1] == ""
    # The second and third are each a heading and what is under it.
    assert lines[second:third] == [
        "COLLECTION ERROR tests/test_b.py",
        "  line 1: `import pytest`",
        "  It uses pytest.skip. What replaces pytest is in the error for tests/test_a.py.",
    ]
    assert lines[third + 1] == "  line 1: `import pytest`"


def test_a_test_that_yields_is_not_reported_as_passed():
    result = run_in_project(
        {
            "tests/test_yields.py": (
                "def test_leftover():\n    assert False\n    yield\n"
                "\n"
                "async def test_async_leftover():\n    assert False\n    yield\n"
            ),
        }
    )
    assert result.exit_code == 1
    assert "0 passed, 1 collection errors" in result.output
    assert "test_leftover() has a `yield` in it." in result.output
    assert "test_async_leftover() has a `yield` in it." in result.output
    assert result.output.count("A test can't yield") == 1


def test_nothing_that_looks_like_a_test_is_left_out_without_a_word():
    result = run_in_project(
        {
            "tests/shared_checks.py": "def test_shared():\n    assert False\n",
            "tests/test_kinds.py": (
                "import unittest\n"
                "\n"
                "from shared_checks import test_shared\n"
                "\n"
                "class TestGroup:\n"
                "    @staticmethod\n"
                "    def test_static():\n"
                "        assert False, 'the static method ran'\n"
                "\n"
                "class UserTests(unittest.TestCase):\n"
                "    def test_it(self):\n"
                "        assert False\n"
            ),
        }
    )
    assert result.exit_code == 1
    assert "UserTests is a unittest.TestCase" in result.output
    assert "test_shared is defined in shared_checks, not in this file" in result.output

    # With those two gone, the static method is a test that runs.
    result = run_in_project(
        {
            "tests/test_kinds.py": (
                "class TestGroup:\n"
                "    @staticmethod\n"
                "    def test_static():\n"
                "        assert False, 'the static method ran'\n"
            ),
        }
    )
    assert result.exit_code == 1
    assert "FAILED tests/test_kinds.py::TestGroup::test_static" in result.output
    assert "the static method ran" in result.output


def test_a_conftest_is_refused_however_the_target_is_written():
    project = make_project(
        {
            "tests/conftest.py": CONFTEST_WITH_A_KID,
            "tests/accounts/test_it.py": "def test_it():\n    assert True\n",
        }
    )
    for target in (
        "tests/accounts",
        "tests/accounts/test_it.py",
        "tests/accounts/test_it.py::test_it",
    ):
        result = run_runner(project, target)
        assert result.exit_code == 1
        assert "COLLECTION ERROR tests/conftest.py" in result.output
        assert "1 passed, 1 collection errors" in result.output


def test_a_case_is_named_for_its_values_where_it_is_reported():
    project = make_project(
        {
            "tests/test_money.py": (
                "from plain.test import cases\n"
                "\n"
                "@cases(('5', 500), ('0.05', 5))\n"
                "def test_parses_dollars_into_cents(written, cents):\n"
                "    assert cents == 0\n"
            ),
        }
    )
    result = run_runner(project)
    test = "tests/test_money.py::test_parses_dollars_into_cents"
    assert f"FAILED {test}[5-500]" in result.output
    assert f"Re-run: plain test '{test}[5-500]'" in result.output

    rerun = run_runner(project, f"{test}[0.05-5]", "--verbose")
    assert "Collected 1 test\n" in rerun.output
    assert f"failed  {test}[0.05-5]" in rerun.output
