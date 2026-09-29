"""
What came of a run, as data.

A `RunReport` is everything the runner knows when a run is over: what was
asked for, what ran, what failed and why, and how the command will exit.
It is put together once. The text reporter prints it and `--json` writes
it as a document, and neither works out anything the other would have to
work out again.
"""

from dataclasses import dataclass

from .execution import RaisedWarning, TestRun
from .failure import CollectionFailure
from .output_capture import NO_OUTPUT, Output

__all__ = []

EXIT_PASSED = 0
# A test failed, or a file couldn't be collected.
EXIT_FAILED = 1
# The command was given something it can't use: a target that isn't there,
# flags that don't go together, a `tests/lifecycle.py` that declares no
# lifecycle.
EXIT_UNUSABLE = 2
# The run couldn't start: setting up the app or a lifecycle failed. The
# tests are no more wrong than they were; what they run on isn't there.
EXIT_SETUP_FAILED = 3
EXIT_NO_TESTS_FOUND = 4
# Stopped from outside, with Ctrl-C. 128 + SIGINT, as a shell reports it.
EXIT_INTERRUPTED = 130

EXIT_CODE_OF_A_STOPPED_RUN = {
    "lifecycle_error": EXIT_UNUSABLE,
    "target_not_found": EXIT_UNUSABLE,
    "setup_error": EXIT_SETUP_FAILED,
    "no_tests_found": EXIT_NO_TESTS_FOUND,
    "interrupted": EXIT_INTERRUPTED,
}


@dataclass(frozen=True, kw_only=True)
class Command:
    """What the run was asked to do."""

    # The command line, as the process was given it.
    argv: tuple[str, ...]
    # Where the command was run from. Every path in a report is relative
    # to it.
    directory: str
    targets: tuple[str, ...]
    # The text `--match` was given.
    match: str | None
    tags: tuple[str, ...]
    exclude_tags: tuple[str, ...]
    fail_fast: bool
    full_values: bool


@dataclass(frozen=True, kw_only=True)
class StoppedRun:
    """Why a run ended before any test was run."""

    # "lifecycle_error", "target_not_found", "setup_error", "no_tests_found"
    # or "interrupted"
    reason: str
    message: str
    traceback: str | None = None
    # What had been written by then, outside any file being collected.
    output: Output = NO_OUTPUT


@dataclass(frozen=True, kw_only=True)
class Counts:
    # The tests the command's targets and options chose.
    selected: int
    passed: int
    failed: int
    skipped: int
    # Chosen and never finished: the run stopped at a failure, with
    # `--fail-fast`, or was interrupted. The test that was running when it
    # was interrupted is one of them.
    not_run: int
    collection_errors: int
    # Distinct warnings, not how many times each was raised.
    warnings: int


@dataclass(frozen=True, kw_only=True)
class RunReport:
    command: Command
    # None when the run ended before any test was run. Then `stopped` says
    # why.
    run: TestRun | None
    stopped: StoppedRun | None
    collection_failures: tuple[CollectionFailure, ...]
    selected: int
    # What was written outside any test and any file being collected:
    # setting up the app, setting up the lifecycles and taking them down.
    # Empty for a stopped run, whose `stopped.output` it is.
    output: Output = NO_OUTPUT

    @property
    def warnings(self) -> tuple[RaisedWarning, ...]:
        return tuple(self.run.warnings) if self.run is not None else ()

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
                warnings=0,
            )
        return Counts(
            selected=self.selected,
            passed=len(run.passed),
            failed=len(run.failed),
            skipped=len(run.skipped),
            not_run=self.selected - len(run.results),
            collection_errors=len(self.collection_failures),
            warnings=len(run.warnings),
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
            return EXIT_CODE_OF_A_STOPPED_RUN[self.stopped.reason]
        return {
            "passed": EXIT_PASSED,
            "failed": EXIT_FAILED,
            "interrupted": EXIT_INTERRUPTED,
        }[self.outcome]
