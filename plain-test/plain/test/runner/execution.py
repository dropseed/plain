"""
Test execution: drives lifecycles around each collected test.
"""

import asyncio
import dataclasses
import inspect
import time
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
)
from .output_capture import Output, OutputCapture

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
class TestRun:
    results: list[TestResult]
    duration: float
    # Set when Ctrl-C stopped the run. The tests after it were not run.
    interrupted: InterruptedTest | None = None
    teardown_errors: list[TeardownError] = field(default_factory=list)

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

    # Track which lifecycles actually set up, so a failure partway through
    # setup still tears down the ones that completed (e.g. drops the test
    # database instead of leaking it).
    started: list[TestLifecycle] = []
    try:
        for lifecycle in lifecycles:
            lifecycle.setup_worker()
            started.append(lifecycle)

        # What setting up wrote is the run's, not the first test's.
        capture.discard()

        for test in tests:
            try:
                result = _run_one(
                    test,
                    lifecycles=lifecycles,
                    full_values=full_values,
                    capture=capture,
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
        for lifecycle in reversed(started):
            # One lifecycle's teardown failure shouldn't skip the others.
            try:
                lifecycle.teardown_worker()
            except Exception as error:
                teardown_errors.append(
                    TeardownError(
                        traceback=format_traceback(error), output=capture.take()
                    )
                )

    return TestRun(
        results=results,
        duration=time.monotonic() - run_start,
        interrupted=interrupted,
        teardown_errors=teardown_errors,
    )


def _run_one(
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
