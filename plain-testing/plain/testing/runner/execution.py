"""
Test execution: drives lifecycles around each collected test.
"""

import asyncio
import dataclasses
import inspect
import sys
import time
import warnings
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field

from ..lifecycle import TestLifecycle
from ..skipping import TestSkipped
from .collection import RunnableTest
from .failure import (
    Failure,
    describe_failure,
    failure_that_could_not_be_described,
    format_traceback,
    shown_path,
)
from .output_capture import NO_OUTPUT, Output, OutputCapture
from .phases import Part

__all__ = []


@dataclass
class TestResult:
    test: RunnableTest
    outcome: str  # "passed" | "failed" | "skipped"
    duration: float = 0.0
    # What a failed test says about its failure, already printed. The
    # exception itself isn't kept: it would hold every frame it passed
    # through, and everything those frames had in hand, until the run ends.
    failure: Failure | None = None
    # Why a skipped test was skipped — from `@skip` or from `skip_test()`.
    skip_reason: str | None = None


@dataclass
class InterruptedTest:
    """The test that was running when the run was stopped from outside."""

    test: RunnableTest
    # What it had written by then.
    output: Output


@dataclass
class TeardownError:
    """A lifecycle that raised while being taken down, after the last test."""

    # Formatted, with the runner's own frames taken off the top.
    traceback: str
    # What had been written since the last test.
    output: Output


@dataclass
class SetupFailure:
    """
    A lifecycle that didn't get through `setup_worker()`: it raised, or it
    wrote its reason and called `sys.exit()`. No test was run.
    """

    # The lifecycle's class: "PostgresTestLifecycle".
    lifecycle: str
    # "ValueError", or "SystemExit" for one that exited.
    error_type: str
    error_message: str
    # Formatted, with the runner's own frames taken off the top.
    traceback: str


@dataclass(frozen=True, kw_only=True)
class RaisedWarning:
    """A warning tests raised, however many times and in however many tests."""

    # "DeprecationWarning"
    category: str
    message: str
    # How many times it was raised, in all the tests that raised it.
    count: int
    # The first test that raised it, and the line of code it was about
    # then. The file is relative to where the run started, when it is under
    # there.
    first_test: str
    file: str
    line: int


@dataclass
class TestRun:
    results: list[TestResult]
    duration: float
    # Set when Ctrl-C stopped the run. The tests after it were not run.
    interrupted: InterruptedTest | None = None
    teardown_errors: list[TeardownError] = field(default_factory=list)
    # Set when the lifecycles couldn't be set up. No test was run.
    setup_failure: SetupFailure | None = None
    # What the lifecycles wrote being set up, before the first test, and
    # being taken down, after the last. It is no test's.
    setup_output: Output = NO_OUTPUT
    teardown_output: Output = NO_OUTPUT
    # Each distinct warning once, in the order first raised.
    warnings: list[RaisedWarning] = field(default_factory=list)
    # How long each lifecycle took to set up and to take down, by its class,
    # and how long the tests took between, first to last.
    lifecycle_setup: tuple[Part, ...] = ()
    lifecycle_teardown: tuple[Part, ...] = ()
    tests_seconds: float = 0.0

    @property
    def passed(self) -> list[TestResult]:
        return [r for r in self.results if r.outcome == "passed"]

    @property
    def failed(self) -> list[TestResult]:
        return [r for r in self.results if r.outcome == "failed"]

    @property
    def skipped(self) -> list[TestResult]:
        return [r for r in self.results if r.outcome == "skipped"]

    @property
    def ok(self) -> bool:
        return not self.failed and self.interrupted is None


def run_tests(
    tests: list[RunnableTest],
    *,
    lifecycles: list[TestLifecycle],
    fail_fast: bool = False,
    full_values: bool = False,
    on_result: Callable[[TestResult], None] | None = None,
    capture: OutputCapture | None = None,
) -> TestRun:
    """
    Run the tests, each inside every lifecycle.

    `capture` is the run's hold on what is written to stdout and stderr. A
    failed test's failure is given what the test wrote, and what a passing
    test wrote is thrown away. Without one, output goes where it always
    went.
    """
    if capture is None:
        # Entered by nobody, it holds nothing and has nothing to give.
        capture = OutputCapture(show_output=True)

    run_start = time.monotonic()
    results: list[TestResult] = []
    interrupted = None
    teardown_errors = []
    setup_failure = None
    setup_output = NO_OUTPUT
    raised_warnings = _RaisedWarnings()
    lifecycle_setup: list[Part] = []
    lifecycle_teardown: list[Part] = []
    tests_seconds = 0.0

    # Track which lifecycles actually set up, so a failure partway through
    # setup still tears down the ones that completed (e.g. drops the test
    # database instead of leaking it).
    started: list[TestLifecycle] = []
    try:
        for lifecycle in lifecycles:
            setup_start = time.monotonic()
            try:
                lifecycle.setup_worker()
            except KeyboardInterrupt:
                raise
            except BaseException as error:
                # SystemExit too: code that can't set up writes why and
                # calls `sys.exit()`, as creating the test database does
                # when the server can't be reached.
                setup_failure = SetupFailure(
                    lifecycle=type(lifecycle).__qualname__,
                    error_type=type(error).__qualname__,
                    error_message=str(error),
                    traceback=format_traceback(error),
                )
                break
            finally:
                lifecycle_setup.append(
                    Part(
                        name=type(lifecycle).__qualname__,
                        seconds=time.monotonic() - setup_start,
                        parts=_what_setup_spent_its_time_on(lifecycle)
                        if setup_failure is None
                        else (),
                    )
                )
            started.append(lifecycle)

        # What setting up wrote is the run's, not the first test's.
        setup_output = capture.take()

        tests_start = time.monotonic()
        try:
            for test in tests if setup_failure is None else ():
                try:
                    result = _run_one(
                        test,
                        lifecycles=lifecycles,
                        full_values=full_values,
                        capture=capture,
                        raised_warnings=raised_warnings,
                    )
                except KeyboardInterrupt:
                    interrupted = InterruptedTest(test=test, output=capture.take())
                    break
                results.append(result)
                if on_result is not None:
                    on_result(result)
                if fail_fast and result.outcome == "failed":
                    break
        finally:
            tests_seconds = time.monotonic() - tests_start
    finally:
        for lifecycle in reversed(started):
            teardown_start = time.monotonic()
            # One lifecycle's teardown failure shouldn't skip the others.
            try:
                lifecycle.teardown_worker()
            except KeyboardInterrupt:
                raise
            except BaseException as error:
                teardown_errors.append(
                    TeardownError(
                        traceback=format_traceback(error), output=capture.take()
                    )
                )
            finally:
                lifecycle_teardown.append(
                    Part(
                        name=type(lifecycle).__qualname__,
                        seconds=time.monotonic() - teardown_start,
                    )
                )

    return TestRun(
        results=results,
        duration=time.monotonic() - run_start,
        interrupted=interrupted,
        teardown_errors=teardown_errors,
        setup_failure=setup_failure,
        setup_output=setup_output,
        # What a teardown that raised wrote is with its error.
        teardown_output=capture.take(),
        warnings=raised_warnings.each_once(),
        lifecycle_setup=tuple(lifecycle_setup),
        lifecycle_teardown=tuple(lifecycle_teardown),
        tests_seconds=tests_seconds,
    )


def _what_setup_spent_its_time_on(lifecycle: TestLifecycle) -> tuple[Part, ...]:
    return tuple(
        Part(name=name, seconds=seconds) for name, seconds in lifecycle.describe_setup()
    )


class _RaisedWarnings:
    """The warnings a run's tests raised, each distinct one kept once."""

    def __init__(self) -> None:
        # The same warning is the same kind saying the same thing, wherever
        # it is raised from: a deprecated function called from two hundred
        # places is one thing to fix. A dict keeps the order they were first
        # raised in.
        self._raised: dict[tuple[str, str], RaisedWarning] = {}

    def add(self, raised: list[warnings.WarningMessage], *, test: RunnableTest) -> None:
        for warning in raised:
            category = warning.category.__qualname__
            message = str(warning.message)
            key = (category, message)
            before = self._raised.get(key)
            if before is None:
                self._raised[key] = RaisedWarning(
                    category=category,
                    message=message,
                    count=1,
                    first_test=test.id,
                    file=shown_path(warning.filename),
                    line=warning.lineno,
                )
            else:
                self._raised[key] = dataclasses.replace(before, count=before.count + 1)

    def each_once(self) -> list[RaisedWarning]:
        return list(self._raised.values())


def _run_one(
    test: RunnableTest,
    *,
    lifecycles: list[TestLifecycle],
    full_values: bool,
    capture: OutputCapture,
    raised_warnings: _RaisedWarnings,
) -> TestResult:
    """
    Warnings the test raises are kept for the run to count, whatever comes
    of the test. Python would have written each to stderr, where a passing
    test's is thrown away with the rest of what it wrote.
    """
    with warnings.catch_warnings(record=True) as raised:
        # Python ignores a DeprecationWarning unless it is raised by the
        # script being run, which a test never is. A test run is where a
        # deprecation is wanted: it says what to change before it breaks.
        # With `-W` or PYTHONWARNINGS the filters are as they were given.
        if not sys.warnoptions:
            warnings.simplefilter("always", DeprecationWarning)
            warnings.simplefilter("always", PendingDeprecationWarning)
        result = _run_one_with_its_lifecycles(
            test, lifecycles=lifecycles, full_values=full_values, capture=capture
        )
    raised_warnings.add(raised, test=test)
    return result


def _run_one_with_its_lifecycles(
    test: RunnableTest,
    *,
    lifecycles: list[TestLifecycle],
    full_values: bool,
    capture: OutputCapture,
) -> TestResult:
    if test.skip_reason is not None:
        return TestResult(test=test, outcome="skipped", skip_reason=test.skip_reason)

    def described(error: BaseException) -> Failure:
        try:
            return describe_failure(
                error,
                test=test,
                describers=[lifecycle.describe_value for lifecycle in lifecycles],
                full_values=full_values,
            )
        except Exception as while_describing:
            return failure_that_could_not_be_described(
                error, test=test, while_describing=while_describing
            )

    start = time.monotonic()
    described_error = None
    failure = None
    try:
        with ExitStack() as stack:
            for lifecycle in lifecycles:
                stack.enter_context(lifecycle.around_test(test))
            try:
                outcome = test.func()
                if inspect.iscoroutine(outcome):
                    asyncio.run(outcome)
            except KeyboardInterrupt, TestSkipped:
                raise
            except BaseException as error:
                # Described here, before the lifecycles exit. What the test
                # had in hand is still as the test left it: its transaction
                # hasn't been rolled back, its settings haven't been put
                # back.
                described_error = error
                failure = described(error)
                raise
    except KeyboardInterrupt:
        raise
    except TestSkipped as skipped:
        # Raised by `skip_test()` in the test body. It left through the
        # lifecycles' `with` blocks like any exception, so they have exited.
        capture.discard()
        return TestResult(
            test=test,
            outcome="skipped",
            duration=time.monotonic() - start,
            skip_reason=skipped.reason,
        )
    except BaseException as error:
        if failure is None or error is not described_error:
            # A lifecycle raised, entering or exiting. Its error is the
            # one that came out, with the test's own above it in the
            # traceback if the test had failed too.
            failure = described(error)
        # Taken now that the lifecycles have exited: what they wrote on the
        # way out (a rollback that failed) is the test's too.
        output = capture.take()
        failure = dataclasses.replace(
            failure, stdout=output.stdout, stderr=output.stderr
        )
        return TestResult(
            test=test,
            outcome="failed",
            duration=time.monotonic() - start,
            failure=failure,
        )

    capture.discard()
    return TestResult(test=test, outcome="passed", duration=time.monotonic() - start)
