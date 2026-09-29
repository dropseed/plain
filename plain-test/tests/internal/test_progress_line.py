"""
What the text reporter prints while tests run: nothing for a test that
passes, a line per test with `verbose`, and with `progress` one line that is
written over itself and erased before the report.
"""

import io

from plain.test.runner.collection import RunnableTest
from plain.test.runner.execution import TestResult
from plain.test.runner.reporting import TextReporter

ERASE = "\r\x1b[K"


def result_of(name, outcome):
    test = RunnableTest(id=f"tests/test_it.py::{name}", func=lambda: None)
    return TestResult(test=test, outcome=outcome, skip_reason="not today")


def reporter_that_ran(*outcomes, verbose=False, progress=False):
    out = io.StringIO()
    reporter = TextReporter(
        out=out, err=io.StringIO(), verbose=verbose, progress=progress
    )
    reporter.collected(len(outcomes))
    for number, outcome in enumerate(outcomes):
        reporter.result(result_of(f"test_{number}", outcome))
    return reporter, out


def test_a_test_prints_nothing_as_it_finishes():
    _, out = reporter_that_ran("passed", "failed", "skipped")
    assert out.getvalue() == "Collected 3 tests\n"


def test_verbose_prints_a_line_for_each_test_with_its_outcome_in_lower_case():
    _, out = reporter_that_ran("passed", "failed", "skipped", verbose=True)
    assert out.getvalue().splitlines() == [
        "Collected 3 tests",
        "passed  tests/test_it.py::test_0 (0.000s)",
        "failed  tests/test_it.py::test_1 (0.000s)",
        "skipped tests/test_it.py::test_2 (not today)",
    ]


def test_progress_is_one_line_written_over_itself():
    _, out = reporter_that_ran("passed", "failed", "passed", progress=True)
    assert out.getvalue() == (
        "Collected 3 tests\n"
        f"{ERASE}1 of 3"
        f"{ERASE}2 of 3, 1 failed"
        f"{ERASE}3 of 3, 1 failed"
    )


def test_progress_is_erased_so_none_of_it_is_left_on_the_terminal():
    reporter, out = reporter_that_ran("passed", progress=True)
    reporter._erase_progress()
    assert out.getvalue().endswith(f"{ERASE}1 of 1{ERASE}")

    # Erased once. With nothing shown, there is nothing to erase.
    reporter._erase_progress()
    assert out.getvalue().count(ERASE) == 2


def test_verbose_has_its_lines_and_no_progress_line():
    _, out = reporter_that_ran("passed", verbose=True, progress=True)
    assert ERASE not in out.getvalue()
