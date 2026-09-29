"""
What a test writes is held while it runs. A test that fails has it printed
with its failure, and a test that passes has it thrown away.

Each test runs the command on a project made for it.
"""

from plain.test import cases
from plain_test_helpers import block, run_in_project, section

WRITES_EVERY_WAY = (
    "import logging\n"
    "import os\n"
    "import subprocess\n"
    "import sys\n"
    "\n"
    "# Configured before any test runs, as an app's logging is. The handler\n"
    "# keeps the stream it was given.\n"
    "logger = logging.getLogger('shop')\n"
    "logger.addHandler(logging.StreamHandler(sys.stderr))\n"
    "logger.propagate = False\n"
    "\n"
    "def write_every_way():\n"
    "    print('printed')\n"
    "    sys.stdout.write('written to sys.stdout\\n')\n"
    "    os.write(1, b'written to descriptor 1\\n')\n"
    "    subprocess.run(\n"
    "        [sys.executable, '-c', 'print(\"printed by a subprocess\")'],\n"
    "        check=True,\n"
    "    )\n"
    "    print('printed to stderr', file=sys.stderr)\n"
    "    logger.warning('logged')\n"
    "    os.write(2, b'written to descriptor 2\\n')\n"
    "\n"
)


def test_what_a_passing_test_writes_is_not_printed():
    result = run_in_project(
        {
            "tests/test_it.py": WRITES_EVERY_WAY
            + "def test_passes():\n    write_every_way()\n"
        }
    )
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        "Collected 1 test",
        ".",
        "",
        result.stdout.splitlines()[-1],
    ]
    assert result.stdout.splitlines()[-1].startswith("1 passed in ")


def test_what_a_failing_test_writes_is_printed_with_its_failure():
    result = run_in_project(
        {
            "tests/test_it.py": WRITES_EVERY_WAY
            + "def test_fails():\n    write_every_way()\n    assert False\n"
        }
    )
    assert result.exit_code == 1
    # Each stream in the order it was written in, whatever wrote it.
    assert block(result.stdout, "stdout:") == [
        "stdout:",
        "  printed",
        "  written to sys.stdout",
        "  written to descriptor 1",
        "  printed by a subprocess",
    ]
    assert block(result.stdout, "stderr:") == [
        "stderr:",
        "  printed to stderr",
        "  logged",
        "  written to descriptor 2",
    ]
    # With the failure, and nowhere else.
    assert result.stderr == ""
    assert result.stdout.count("printed by a subprocess") == 1


def test_a_failure_is_given_only_what_its_own_test_wrote():
    result = run_in_project(
        {
            "tests/test_it.py": (
                "from plain.test import skip_test\n"
                "\n"
                "def test_a_passes():\n"
                "    print('from the test that passed')\n"
                "\n"
                "def test_b_skips():\n"
                "    print('from the test that skipped')\n"
                "    skip_test('not today')\n"
                "\n"
                "def test_c_fails():\n"
                "    print('from the test that failed')\n"
                "    assert False\n"
                "\n"
                "def test_d_fails_too():\n"
                "    assert False\n"
            )
        }
    )
    assert result.exit_code == 1
    assert block(result.stdout, "stdout:") == [
        "stdout:",
        "  from the test that failed",
    ]
    assert result.output.count("stdout:") == 1
    assert "from the test that passed" not in result.output
    assert "from the test that skipped" not in result.output


LIFECYCLE_THAT_WRITES = (
    "from contextlib import contextmanager\n"
    "\n"
    "from plain.test import TestLifecycle\n"
    "\n"
    "\n"
    "class AppTestLifecycle(TestLifecycle):\n"
    "    def setup_worker(self):\n"
    "        print('setting up the run')\n"
    "\n"
    "    def teardown_worker(self):\n"
    "        print('taking down the run')\n"
    "\n"
    "    @contextmanager\n"
    "    def around_test(self, test):\n"
    "        print('entering')\n"
    "        try:\n"
    "            yield\n"
    "        finally:\n"
    "            print('exiting')\n"
)


def test_what_a_lifecycle_writes_around_a_test_is_that_tests():
    result = run_in_project(
        {
            "tests/lifecycle.py": LIFECYCLE_THAT_WRITES,
            "tests/test_it.py": (
                "def test_fails():\n    print('in the test')\n    assert False\n"
            ),
        }
    )
    assert result.exit_code == 1
    failure = section(result.stdout, "FAILED tests/test_it.py::test_fails")
    assert block(failure, "stdout:") == [
        "stdout:",
        "  entering",
        "  in the test",
        "  exiting",
    ]
    # What setting the run up and taking it down wrote is the run's, not
    # the first test's or the last's.
    assert "the run" not in failure
    assert block(section(result.stdout, "WRITTEN OUTSIDE ANY TEST"), "stdout:") == [
        "stdout:",
        "  setting up the run",
        "  taking down the run",
    ]


def test_what_is_written_outside_any_test_is_printed_when_every_test_passes():
    result = run_in_project(
        {
            "tests/lifecycle.py": LIFECYCLE_THAT_WRITES,
            "tests/test_it.py": "def test_passes():\n    print('in the test')\n",
        }
    )
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout.splitlines()[:-1] == [
        "Collected 1 test",
        ".",
        "",
        "WRITTEN OUTSIDE ANY TEST",
        "",
        "  stdout:",
        "    setting up the run",
        "    taking down the run",
        "",
    ]


def test_what_setting_up_the_app_and_loading_the_lifecycle_wrote_is_the_runs():
    result = run_in_project(
        {
            "tests/lifecycle.py": "import sys\n\nprint('the database is slow today', file=sys.stderr)\n"
            + LIFECYCLE_THAT_WRITES,
            "tests/test_it.py": "def test_passes():\n    pass\n",
        }
    )
    assert result.exit_code == 0
    written = section(result.stdout, "WRITTEN OUTSIDE ANY TEST")
    assert block(written, "stderr:") == ["stderr:", "  the database is slow today"]


@cases("-s", "--show-output")
def test_show_output_lets_everything_through_as_it_is_written(flag):
    result = run_in_project(
        {
            "tests/lifecycle.py": LIFECYCLE_THAT_WRITES,
            "tests/test_it.py": (
                "import sys\n"
                "\n"
                "def test_passes():\n"
                "    print('in the test that passes')\n"
                "\n"
                "def test_fails():\n"
                "    print('to stderr', file=sys.stderr)\n"
                "    assert False\n"
            ),
        },
        flag,
    )
    assert result.exit_code == 1
    assert result.stderr == "to stderr\n"
    # Between the runner's own, where it was written: a progress dot has
    # no line of its own.
    assert "setting up the run\n" in result.stdout
    assert "in the test that passes\n" in result.stdout
    assert "taking down the run\n" in result.stdout
    # It was let through, so the failure has none of it to print.
    assert "stdout:" not in result.output
    assert "stderr:" not in result.output


def test_a_test_that_catches_its_own_output_still_does():
    result = run_in_project(
        {
            "tests/test_it.py": (
                "import contextlib\n"
                "import io\n"
                "import subprocess\n"
                "import sys\n"
                "\n"
                "import click\n"
                "from click.testing import CliRunner\n"
                "\n"
                "from plain.test import capture_logs\n"
                "import logging\n"
                "\n"
                "\n"
                "@click.command()\n"
                "def hello():\n"
                "    click.echo('hello from the command')\n"
                "\n"
                "\n"
                "def test_catches():\n"
                "    with contextlib.redirect_stdout(io.StringIO()) as out:\n"
                "        print('redirected')\n"
                "    assert out.getvalue() == 'redirected\\n'\n"
                "\n"
                "    with contextlib.redirect_stderr(io.StringIO()) as err:\n"
                "        print('redirected too', file=sys.stderr)\n"
                "    assert err.getvalue() == 'redirected too\\n'\n"
                "\n"
                "    result = CliRunner().invoke(hello)\n"
                "    assert result.output == 'hello from the command\\n'\n"
                "\n"
                "    completed = subprocess.run(\n"
                "        [sys.executable, '-c', 'print(\"from a pipe\")'],\n"
                "        capture_output=True, text=True, check=True,\n"
                "    )\n"
                "    assert completed.stdout == 'from a pipe\\n'\n"
                "\n"
                "    with capture_logs('shop') as logs:\n"
                "        logging.getLogger('shop').warning('captured as a record')\n"
                "    assert logs.messages == ['captured as a record']\n"
                "\n"
                "    print('and this was not caught')\n"
                "    assert False\n"
            )
        }
    )
    assert result.exit_code == 1, result.output
    assert "AssertionError" in result.output
    # The one assert that failed is the last one.
    assert block(result.stdout, "assert ") == ["assert False"]
    # What the test caught, it kept.
    assert block(result.stdout, "stdout:") == [
        "stdout:",
        "  and this was not caught",
    ]


def test_breakpoint_gets_the_terminal():
    result = run_in_project(
        {
            "tests/test_it.py": (
                "def test_stops():\n"
                "    print('before the breakpoint')\n"
                "    total = 41\n"
                "    breakpoint()\n"
                "    print('after the breakpoint')\n"
                "\n"
                "def test_next():\n"
                "    print('held again')\n"
            )
        },
        typed="p total + 1\ncontinue\n",
    )
    assert result.exit_code == 0, result.output
    assert "breakpoint(): output is let through" in result.stderr
    # The debugger stopped in the test, where `total` is, and what it
    # printed was seen.
    assert "test_stops()" in result.stdout
    assert "(Pdb) 42" in result.stdout.splitlines()
    # From the breakpoint to the end of that test, output is let through.
    assert "after the breakpoint" in result.stdout
    assert "before the breakpoint" not in result.output
    assert "held again" not in result.output


def test_a_run_stopped_with_ctrl_c_prints_what_it_has():
    result = run_in_project(
        {
            "tests/lifecycle.py": LIFECYCLE_THAT_WRITES,
            "tests/test_it.py": (
                "def test_a_fails():\n"
                "    assert 1 == 2\n"
                "\n"
                "def test_b_is_stopped():\n"
                "    print('got this far')\n"
                "    raise KeyboardInterrupt\n"
                "\n"
                "def test_c_is_never_run():\n"
                "    print('never written')\n"
            ),
        }
    )
    assert result.exit_code == 130
    assert "FAILED tests/test_it.py::test_a_fails" in result.stdout
    assert "INTERRUPTED tests/test_it.py::test_b_is_stopped" in result.stdout
    interrupted = section(result.stdout, "INTERRUPTED tests/test_it.py")
    assert block(interrupted, "stdout:") == [
        "stdout:",
        "  entering",
        "  got this far",
        "  exiting",
    ]
    assert "never written" not in result.output
    assert result.stdout.splitlines()[-1].startswith(
        "Interrupted: 0 passed, 1 failed, 2 not run in "
    )
    assert "Traceback" not in result.stderr


def test_code_that_exits_is_a_failure_with_what_it_wrote():
    result = run_in_project(
        {
            "tests/test_it.py": (
                "import sys\n"
                "\n"
                "def test_exits():\n"
                "    print('about to exit')\n"
                "    sys.exit(3)\n"
                "\n"
                "def test_after():\n"
                "    pass\n"
            )
        }
    )
    assert result.exit_code == 1
    assert "SystemExit: 3" in result.stdout
    assert block(result.stdout, "stdout:") == ["stdout:", "  about to exit"]
    assert result.stdout.splitlines()[-1].startswith("1 passed, 1 failed in ")


PRINTS_A_LOT = (
    "def test_prints_a_lot():\n"
    "    print('the first line')\n"
    "    for number in range(5_000):\n"
    "        print(f'line {number:04}')\n"
    "    assert False\n"
)


def test_a_lot_of_output_is_cut_at_the_start_and_says_so():
    result = run_in_project({"tests/test_it.py": PRINTS_A_LOT})
    assert result.exit_code == 1
    printed = block(result.stdout, "stdout:")
    # 5,000 lines of 10 characters and the first line's 15. The last 10,000
    # are kept.
    assert printed[1] == (
        "  ... 40,015 characters before this (--full-values prints them)"
    )
    assert printed[-1] == "  line 4999"
    assert len(printed) == 2 + 1_000
    assert "the first line" not in result.output


def test_full_values_prints_all_the_output():
    result = run_in_project({"tests/test_it.py": PRINTS_A_LOT}, "--full-values")
    printed = block(result.stdout, "stdout:")
    assert printed[1] == "  the first line"
    assert len(printed) == 1 + 1 + 5_000


def test_megabytes_from_a_passing_test_go_nowhere():
    result = run_in_project(
        {
            "tests/test_it.py": (
                "import os\n"
                "\n"
                "def test_writes_megabytes():\n"
                "    for _ in range(64):\n"
                "        os.write(1, b'x' * 1024 * 1024)\n"
                "\n"
                "def test_fails_after():\n"
                "    print('small')\n"
                "    assert False\n"
            )
        }
    )
    assert result.exit_code == 1
    assert block(result.stdout, "stdout:") == ["stdout:", "  small"]
    assert len(result.stdout) < 2_000


def test_what_loading_a_file_wrote_is_printed_with_its_collection_error():
    result = run_in_project(
        {
            "tests/test_a_fine.py": (
                "print('loading the file that loads')\n\ndef test_ok():\n    pass\n"
            ),
            "tests/test_b_broken.py": (
                "print('loading the file that does not')\nLIMIT = UNDEFINED_NAME\n"
            ),
        }
    )
    assert result.exit_code == 1
    assert "COLLECTION ERROR tests/test_b_broken.py" in result.stdout
    assert block(result.stdout, "stdout:") == [
        "stdout:",
        "  loading the file that does not",
    ]
    assert "loading the file that loads" not in result.output


SETUP_THAT_RAISES = (
    "from plain.test import TestLifecycle\n"
    "\n"
    "\n"
    "class AppTestLifecycle(TestLifecycle):\n"
    "    def setup_worker(self):\n"
    "        print('connecting to the database')\n"
    "        raise RuntimeError('no database')\n"
)

SETUP_THAT_EXITS = (
    "import sys\n"
    "\n"
    "from plain.test import TestLifecycle\n"
    "\n"
    "\n"
    "class AppTestLifecycle(TestLifecycle):\n"
    "    def setup_worker(self):\n"
    "        print('Got an error creating the test database', file=sys.stderr)\n"
    "        sys.exit(2)\n"
)


def test_a_lifecycle_that_cannot_be_set_up_is_reported_with_what_it_wrote():
    result = run_in_project(
        {
            "tests/lifecycle.py": SETUP_THAT_RAISES,
            "tests/test_it.py": "def test_one():\n    pass\n",
        }
    )
    assert result.exit_code == 3
    assert result.stderr.splitlines()[0] == (
        "AppTestLifecycle.setup_worker() raised RuntimeError: no database"
    )
    # Where it was raised, without the runner's own steps above it.
    assert "tests/lifecycle.py" in result.stderr
    assert "plain/test/runner" not in result.stderr
    assert block(result.stderr, "stdout:") == [
        "stdout:",
        "  connecting to the database",
    ]
    assert result.stderr.splitlines()[-1] == "No test was run."
    assert result.stdout == "Collected 1 test\n"


def test_a_lifecycle_that_exits_while_being_set_up_is_not_a_silent_run():
    # What creating the test database does when the server can't be
    # reached: it writes why to stderr and calls `sys.exit(2)`.
    result = run_in_project(
        {
            "tests/lifecycle.py": SETUP_THAT_EXITS,
            "tests/test_it.py": "def test_one():\n    pass\n",
        }
    )
    assert result.exit_code == 3
    assert result.stderr.splitlines()[0] == (
        "AppTestLifecycle.setup_worker() exited, with 2."
    )
    assert block(result.stderr, "stderr:") == [
        "stderr:",
        "  Got an error creating the test database",
    ]
    assert result.stderr.splitlines()[-1] == "No test was run."


def test_an_app_that_cannot_be_set_up_is_reported_with_what_it_wrote():
    result = run_in_project(
        {
            "app/settings.py": (
                "print('reading the settings')\n"
                "raise RuntimeError('PAYMENTS_URL must be set')\n"
            ),
            "tests/test_it.py": "def test_one():\n    pass\n",
        }
    )
    assert result.exit_code == 3
    assert "Setting up the app raised RuntimeError: PAYMENTS_URL must be set" in (
        result.stderr
    )
    assert block(result.stderr, "stdout:") == ["stdout:", "  reading the settings"]
    assert result.stderr.splitlines()[-1] == "No test was run."
    assert result.stdout == ""


def test_code_that_exits_while_a_file_is_loaded_loses_nothing():
    result = run_in_project(
        {
            "tests/test_it.py": (
                "import sys\n\nprint('this machine has no license')\nsys.exit(4)\n"
            ),
        }
    )
    assert "this machine has no license" in result.output


def test_a_lifecycle_that_fails_being_taken_down_is_reported():
    result = run_in_project(
        {
            "tests/lifecycle.py": (
                "from plain.test import TestLifecycle\n"
                "\n"
                "\n"
                "class AppTestLifecycle(TestLifecycle):\n"
                "    def teardown_worker(self):\n"
                "        print('dropping the database')\n"
                "        raise RuntimeError('still in use')\n"
            ),
            "tests/test_it.py": "def test_one():\n    pass\n",
        }
    )
    assert result.exit_code == 0
    assert "TEARDOWN ERROR" in result.stdout
    assert "RuntimeError: still in use" in result.stdout
    assert block(result.stdout, "stdout:") == ["stdout:", "  dropping the database"]


def test_a_lifecycle_file_that_cannot_be_used_is_shown_with_what_it_wrote():
    result = run_in_project(
        {
            "tests/lifecycle.py": (
                "print('loading the lifecycle')\n\nclass AppTestLifecycle:\n    pass\n"
            ),
            "tests/test_it.py": "def test_one():\n    pass\n",
        }
    )
    assert result.exit_code == 2
    assert "doesn't define a TestLifecycle subclass" in result.stderr
    assert "loading the lifecycle" in result.stderr


@cases(
    ({"tests/test_it.py": "def test_one():\n    print('x')\n"}, (), 0),
    ({"tests/test_it.py": "def test_one():\n    assert False\n"}, (), 1),
    ({"tests/test_it.py": "def test_one():\n    pass\n"}, ("tests/nope.py",), 2),
    ({"tests/helper.py": "print('x')\n"}, (), 5),
)
def test_holding_output_changes_no_exit_code(files, arguments, exit_code):
    assert run_in_project(files, *arguments).exit_code == exit_code
    assert run_in_project(files, "-s", *arguments).exit_code == exit_code


WARNS = (
    "import warnings\n"
    "\n"
    "\n"
    "def old_price():\n"
    "    warnings.warn('old_price() is going away', DeprecationWarning, stacklevel=2)\n"
    "\n"
    "\n"
    "def test_a_warns():\n"
    "    old_price()\n"
    "    old_price()\n"
    "\n"
    "\n"
    "def test_b_warns_too():\n"
    "    old_price()\n"
    "    warnings.warn('the till is empty', RuntimeWarning, stacklevel=1)\n"
    "\n"
    "\n"
    "def test_c_is_quiet():\n"
    "    pass\n"
)


def test_warnings_are_counted_and_listed_once_each():
    result = run_in_project({"tests/test_it.py": WARNS})
    assert result.exit_code == 0
    assert result.stderr == ""
    # Once, however many places and tests it was raised from.
    assert section(result.stdout, "WARNINGS").splitlines() == [
        "WARNINGS",
        "",
        "  DeprecationWarning: old_price() is going away",
        (
            "    raised 3 times, first at tests/test_it.py:9"
            " in tests/test_it.py::test_a_warns"
        ),
        "  RuntimeWarning: the till is empty",
        (
            "    raised once, first at tests/test_it.py:15"
            " in tests/test_it.py::test_b_warns_too"
        ),
    ]
    assert result.stdout.splitlines()[-1].startswith("3 passed, 2 warnings in ")


def test_a_run_with_no_warnings_says_nothing_of_them():
    result = run_in_project({"tests/test_it.py": "def test_one():\n    pass\n"})
    assert "WARNINGS" not in result.output
    assert "warning" not in result.stdout.splitlines()[-1]
