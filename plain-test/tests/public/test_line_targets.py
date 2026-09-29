"""
`plain test tests/test_signup.py:42` runs the test line 42 is in.
"""

import json

from plain.test import case, cases
from plain_test_helpers import make_project, run_runner

# The line each thing is on is what these tests are about.
PRICES = (
    "from plain.test import cases, tag\n"  # 1
    "\n"  # 2
    "RATE = 2\n"  # 3
    "\n"  # 4
    "\n"  # 5
    "def helper():\n"  # 6
    "    return RATE\n"  # 7
    "\n"  # 8
    "\n"  # 9
    "def test_first():\n"  # 10
    "    assert helper() == 2\n"  # 11
    "\n"  # 12
    "\n"  # 13
    '@tag("slow")\n'  # 14
    "@cases(\n"  # 15
    "    1,\n"  # 16
    "    2,\n"  # 17
    ")\n"  # 18
    "def test_with_cases(number):\n"  # 19
    "    total = number * RATE\n"  # 20
    "\n"  # 21
    "    assert total > 0\n"  # 22
    "\n"  # 23
    "\n"  # 24
    "async def test_last():\n"  # 25
    "    assert True\n"  # 26
)


def tests_run(result):
    """The ids of the tests a verbose run ran, in order."""
    ran = []
    for line in result.stdout.splitlines():
        outcome, _, rest = line.partition(" ")
        if outcome in ("passed", "failed", "skipped"):
            ran.append(rest.split()[0])
    return ran


def prices_project():
    return make_project(
        {
            "tests/test_prices.py": PRICES,
            "tests/test_other.py": "def test_other():\n    assert True\n",
        }
    )


@cases(
    case(10, ["test_first"], id="the line it is defined on"),
    case(11, ["test_first"], id="a line of its body"),
    case(14, ["test_with_cases[1]", "test_with_cases[2]"], id="its first decorator"),
    case(17, ["test_with_cases[1]", "test_with_cases[2]"], id="inside a decorator"),
    case(21, ["test_with_cases[1]", "test_with_cases[2]"], id="a blank line in it"),
    case(22, ["test_with_cases[1]", "test_with_cases[2]"], id="its last line"),
    case(26, ["test_last"], id="the last line of the file"),
)
def test_a_line_runs_the_test_it_is_in(line, names):
    result = run_runner(prices_project(), f"tests/test_prices.py:{line}", "--verbose")
    assert result.exit_code == 0
    assert tests_run(result) == [f"tests/test_prices.py::{name}" for name in names]


@cases(
    case(
        12,
        "It is between test_first (lines 10 to 11) and "
        "test_with_cases (lines 14 to 22).",
        id="between two tests",
    ),
    case(
        7,
        "It is before the first test, test_first (lines 10 to 11).",
        id="in a function that isn't a test",
    ),
    case(
        40,
        "It is after the last test, test_last (lines 25 to 26).",
        id="past the end of the file",
    ),
)
def test_a_line_in_no_test_says_which_tests_are_nearest(line, nearest):
    result = run_runner(prices_project(), f"tests/test_prices.py:{line}")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr == (
        f"No test at tests/test_prices.py:{line}: line {line} is in no test. "
        f"{nearest}\n"
    )


def test_a_line_of_a_file_with_no_tests_says_so():
    project = make_project({"tests/helpers.py": "def make_user():\n    pass\n"})
    result = run_runner(project, "tests/helpers.py:1")
    assert result.exit_code == 2
    assert "line 1 is in no test. The file defines no tests." in result.stderr


def test_a_line_of_a_directory_is_not_a_target():
    result = run_runner(prices_project(), "tests:12")
    assert result.exit_code == 2
    assert result.stderr == (
        "No test at tests:12: tests is a directory, and a line is a line of a file.\n"
    )


def test_a_line_of_a_file_that_isnt_there_is_a_target_that_isnt_there():
    result = run_runner(prices_project(), "tests/test_nope.py:12")
    assert result.exit_code == 2
    assert result.stderr == "No such test target: tests/test_nope.py:12\n"


def test_a_line_goes_with_other_targets_and_with_the_filters():
    project = prices_project()

    result = run_runner(
        project, "tests/test_prices.py:11", "tests/test_other.py", "--verbose"
    )
    assert tests_run(result) == [
        "tests/test_prices.py::test_first",
        "tests/test_other.py::test_other",
    ]

    result = run_runner(
        project, "tests/test_prices.py:20", "--match", "[2]", "--verbose"
    )
    assert tests_run(result) == ["tests/test_prices.py::test_with_cases[2]"]

    result = run_runner(project, "tests/test_prices.py:20", "--exclude-tag", "slow")
    assert result.exit_code == 4
    assert "No tests found" in result.output


def test_a_line_of_a_file_that_cant_be_read_reports_the_file():
    project = make_project({"tests/test_broken.py": "def test_one(:\n    pass\n"})
    result = run_runner(project, "tests/test_broken.py:2")
    assert result.exit_code == 1
    assert "COLLECTION ERROR tests/test_broken.py" in result.output
    assert "SyntaxError" in result.output


def test_a_failure_is_run_again_by_its_name_since_a_line_cant_name_a_case():
    project = make_project(
        {
            "tests/test_prices.py": (
                "from plain.test import cases\n"
                "\n"
                "@cases(1, 0)\n"
                "def test_price(number):\n"
                "    assert number\n"
            )
        }
    )
    result = run_runner(project, "tests/test_prices.py:5")
    assert result.exit_code == 1
    assert "1 passed, 1 failed" in result.output
    assert "Re-run: plain test 'tests/test_prices.py::test_price[0]'" in result.output


def test_the_document_says_a_line_was_in_no_test():
    result = run_runner(prices_project(), "--json", "tests/test_prices.py:12")
    assert result.exit_code == 2
    document = json.loads(result.stdout)
    assert document["command"]["targets"] == ["tests/test_prices.py:12"]
    assert document["stopped"]["reason"] == "target_not_found"
    assert "line 12 is in no test" in document["stopped"]["message"]
