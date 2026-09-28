"""
Test execution: drives lifecycles around each collected test.
"""

import asyncio
import inspect
import time
import traceback
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass

from ..lifecycle import TestLifecycle
from ..skipping import TestSkipped
from .collection import RunnableTest
from .failure import (
    Failure,
    describe_failure,
    failure_that_could_not_be_described,
)

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
class TestRun:
    results: list[TestResult]
    duration: float

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
        return not self.failed


def run_tests(
    tests: list[RunnableTest],
    *,
    lifecycles: list[TestLifecycle],
    fail_fast: bool = False,
    full_values: bool = False,
    on_result: Callable[[TestResult], None] | None = None,
) -> TestRun:
    run_start = time.monotonic()
    results: list[TestResult] = []

    # Track which lifecycles actually set up, so a failure partway through
    # setup still tears down the ones that completed (e.g. drops the test
    # database instead of leaking it).
    started: list[TestLifecycle] = []
    try:
        for lifecycle in lifecycles:
            lifecycle.setup_worker()
            started.append(lifecycle)

        for test in tests:
            result = _run_one(test, lifecycles=lifecycles, full_values=full_values)
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
            except Exception:
                traceback.print_exc()

    return TestRun(results=results, duration=time.monotonic() - run_start)


def _run_one(
    test: RunnableTest, *, lifecycles: list[TestLifecycle], full_values: bool
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
        return TestResult(
            test=test,
            outcome="failed",
            duration=time.monotonic() - start,
            failure=failure,
        )

    return TestResult(test=test, outcome="passed", duration=time.monotonic() - start)
