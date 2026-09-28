"""
What came of a run, as data.

A `RunReport` is everything the runner knows when a run is over: what was
asked for, what ran, what failed and why, and how the command will exit.
It is put together once. The text reporter prints it and `--json` writes
it as a document, and neither works out anything the other would have to
work out again.
"""

from dataclasses import dataclass

from .execution import TestRun
from .failure import CollectionFailure
from .output_capture import NO_OUTPUT, Output

__all__ = []

EXIT_PASSED = 0
EXIT_FAILED = 1
# The run couldn't start: the command was given something it can't use.
EXIT_STOPPED = 2
EXIT_NO_TESTS_FOUND = 5
# Stopped from outside, with Ctrl-C. 128 + SIGINT, as a shell reports it.
EXIT_INTERRUPTED = 130


@dataclass(frozen=True, kw_only=True)
class Command:
    """What the run was asked to do."""

    # Where the command was run from. Every path in a report is relative
    # to it.
    directory: str
    targets: tuple[str, ...]
    keyword: str | None
    tags: tuple[str, ...]
    exclude_tags: tuple[str, ...]
    fail_fast: bool
    full_values: bool


@dataclass(frozen=True, kw_only=True)
class StoppedRun:
    """Why a run ended before any test was run."""

    # "lifecycle_error", "target_not_found" or "no_tests_found"
    reason: str
    message: str
    traceback: str | None = None
    # What had been written by then.
    output: Output = NO_OUTPUT


@dataclass(frozen=True, kw_only=True)
class Counts:
    # The tests the command's targets and options chose.
    selected: int
    passed: int
    failed: int
    skipped: int
    # Chosen and never started: the run stopped at a failure, with
    # `--fail-fast`, or was interrupted.
    not_run: int
    collection_errors: int


@dataclass(frozen=True, kw_only=True)
class RunReport:
    command: Command
    # None when the run ended before any test was run. Then `stopped` says
    # why.
    run: TestRun | None
    stopped: StoppedRun | None
    collection_failures: tuple[CollectionFailure, ...]
    selected: int

    @property
    def counts(self) -> Counts:
        run = self.run
        if run is None:
            return Counts(
                selected=self.selected,
                passed=0,
                failed=0,
                skipped=0,
                not_run=self.selected,
                collection_errors=len(self.collection_failures),
            )
        return Counts(
            selected=self.selected,
            passed=len(run.passed),
            failed=len(run.failed),
            skipped=len(run.skipped),
            not_run=self.selected - len(run.results),
            collection_errors=len(self.collection_failures),
        )

    @property
    def outcome(self) -> str:
        """ "passed", "failed", "interrupted" or "stopped" """
        if self.stopped is not None:
            return "stopped"
        assert self.run is not None
        if self.run.interrupted is not None:
            return "interrupted"
        if self.run.failed or self.collection_failures:
            return "failed"
        return "passed"

    @property
    def exit_code(self) -> int:
        if self.stopped is not None:
            if self.stopped.reason == "no_tests_found":
                return EXIT_NO_TESTS_FOUND
            return EXIT_STOPPED
        return {
            "passed": EXIT_PASSED,
            "failed": EXIT_FAILED,
            "interrupted": EXIT_INTERRUPTED,
        }[self.outcome]
