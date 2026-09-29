"""
The `plain test` command end to end: a project on disk, run in its own
process, judged by what it prints and how it exits.
"""

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
    result = run_in_project({"tests/test_skips.py": SKIPPING_TESTS}, "-v")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert (
        "SKIPPED tests/test_skips.py::test_decides_for_itself "
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
        "-k",
        "--tag",
        "--exclude-tag",
        "-x",
        "--fail-fast",
        "-v",
        "--full-values",
    ):
        assert flag in completed.stdout
    assert "[TARGETS]..." in completed.stdout
    assert "tests/test_signup.py::test_welcome" in completed.stdout
    # The help is what was asked for. No test ran to produce it.
    assert "Collected" not in completed.stdout


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
        rerun = run_pasted(root, f"{command} -v", shell=shell)
        assert "Collected 1 test\n" in rerun.output
        failed_lines = [
            line for line in rerun.output.splitlines() if line.startswith("FAILED ")
        ]
        # Verbose prints the result line, then the failure block's heading.
        assert len(failed_lines) == 2
        rerun_ids.append(failed_lines[1].removeprefix("FAILED "))

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

    rerun = run_runner(project, f"{test}[0.05-5]", "-v")
    assert "Collected 1 test\n" in rerun.output
    assert f"FAILED  {test}[0.05-5]" in rerun.output
