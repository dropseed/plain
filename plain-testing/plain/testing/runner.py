"""
Test execution: drives lifecycles around each collected test.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import traceback
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from plain.test.lifecycle import TestLifecycle

from .collection import CollectedTest

__all__ = ["TestRun", "TestResult", "run_tests"]

_INTERNAL_DIR = str(Path(__file__).parent)


@dataclass
class TestResult:
    test: CollectedTest
    outcome: str  # "passed" | "failed" | "skipped"
    duration: float = 0.0
    error: BaseException | None = None
    traceback_text: str = ""


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
    tests: list[CollectedTest],
    *,
    lifecycles: list[TestLifecycle],
    fail_fast: bool = False,
    on_result=None,
) -> TestRun:
    run_start = time.monotonic()
    results: list[TestResult] = []

    for lifecycle in lifecycles:
        lifecycle.setup_worker()

    try:
        for test in tests:
            result = _run_one(test, lifecycles=lifecycles)
            results.append(result)
            if on_result is not None:
                on_result(result)
            if fail_fast and result.outcome == "failed":
                break
    finally:
        for lifecycle in reversed(lifecycles):
            lifecycle.teardown_worker()

    return TestRun(results=results, duration=time.monotonic() - run_start)


def _run_one(test: CollectedTest, *, lifecycles: list[TestLifecycle]) -> TestResult:
    if test.skip_reason is not None:
        return TestResult(test=test, outcome="skipped")

    start = time.monotonic()
    try:
        with ExitStack() as stack:
            for lifecycle in lifecycles:
                stack.enter_context(lifecycle.around_test(test))
            outcome = test.func()
            if inspect.iscoroutine(outcome):
                asyncio.run(outcome)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return TestResult(
            test=test,
            outcome="failed",
            duration=time.monotonic() - start,
            error=e,
            traceback_text=_format_traceback(e),
        )

    return TestResult(test=test, outcome="passed", duration=time.monotonic() - start)


def _format_traceback(error: BaseException) -> str:
    """Format a traceback with the runner's own frames trimmed off the top."""
    tb = error.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        if not filename.startswith(_INTERNAL_DIR) and "contextlib" not in filename:
            break
        tb = tb.tb_next

    return "".join(
        traceback.format_exception(type(error), error, tb or error.__traceback__)
    )
