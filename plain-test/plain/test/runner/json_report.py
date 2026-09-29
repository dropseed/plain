"""
Test output as one JSON document, for `--json`.

The document is a `RunReport` written out. Everything the runner knew
separately is a field of its own: nothing has to be read out of a string
to find a file, a line, a test or a value.

Every object of one kind has the same fields, whatever happened. A field
with nothing to say is `null`, or an empty list, or an empty string, and is
still there.
"""

import json
from typing import Any, TextIO

from .execution import TestResult
from .failure import CollectionFailure, Failure, where_defined
from .output_capture import StreamOutput
from .printing import PrintedValue
from .report import RunReport

__all__ = []

# Raised when a field is renamed, removed, or changes what it means. A
# field that is added doesn't raise it.
DOCUMENT_VERSION = 1


def document_text(report: RunReport, *, list_passed: bool) -> str:
    return json.dumps(document(report, list_passed=list_passed), indent=2)


def document(report: RunReport, *, list_passed: bool) -> dict[str, Any]:
    run = report.run
    counts = report.counts
    command = report.command

    tests = []
    interrupted = None
    teardown_errors = []
    if run is not None:
        tests = [
            _test(result)
            for result in run.results
            if list_passed or result.outcome != "passed"
        ]
        if run.interrupted is not None:
            file, line = where_defined(run.interrupted.test)
            interrupted = {
                "id": run.interrupted.test.id,
                "file": file,
                "line": line,
                "stdout": _stream(run.interrupted.output.stdout),
                "stderr": _stream(run.interrupted.output.stderr),
            }
        teardown_errors = [
            {
                "traceback": error.traceback,
                "stdout": _stream(error.output.stdout),
                "stderr": _stream(error.output.stderr),
            }
            for error in run.teardown_errors
        ]

    stopped = None
    if report.stopped is not None:
        stopped = {
            "reason": report.stopped.reason,
            "message": report.stopped.message,
            "traceback": report.stopped.traceback,
            "stdout": _stream(report.stopped.output.stdout),
            "stderr": _stream(report.stopped.output.stderr),
        }

    return {
        "version": DOCUMENT_VERSION,
        "outcome": report.outcome,
        "exit_code": report.exit_code,
        "duration": round(run.duration, 4) if run is not None else 0.0,
        "command": {
            "argv": list(command.argv),
            "directory": command.directory,
            "targets": list(command.targets),
            "keyword": command.keyword,
            "tags": list(command.tags),
            "exclude_tags": list(command.exclude_tags),
            "fail_fast": command.fail_fast,
            "full_values": command.full_values,
        },
        "counts": {
            "selected": counts.selected,
            "passed": counts.passed,
            "failed": counts.failed,
            "skipped": counts.skipped,
            "not_run": counts.not_run,
            "collection_errors": counts.collection_errors,
            "warnings": counts.warnings,
        },
        "tests_listed": "all" if list_passed else "failed_and_skipped",
        "tests": tests,
        "collection_errors": [
            _collection_error(failure) for failure in report.collection_failures
        ],
        "warnings": [
            {
                "category": warning.category,
                "message": warning.message,
                "count": warning.count,
                "first_test": warning.first_test,
                "file": warning.file,
                "line": warning.line,
            }
            for warning in report.warnings
        ],
        "stopped": stopped,
        "interrupted": interrupted,
        "teardown_errors": teardown_errors,
        # What was written outside any test: setting up the app and the
        # lifecycles, and taking them down. A stopped run's is in `stopped`.
        "stdout": _stream(report.output.stdout),
        "stderr": _stream(report.output.stderr),
    }


def _test(result: TestResult) -> dict[str, Any]:
    file, line = where_defined(result.test)
    return {
        "id": result.test.id,
        "file": file,
        "line": line,
        "name": result.test.name,
        "tags": list(result.test.tags),
        "outcome": result.outcome,
        "duration": round(result.duration, 4),
        "skip_reason": result.skip_reason,
        "failure": _failure(result.failure) if result.failure is not None else None,
    }


def _failure(failure: Failure) -> dict[str, Any]:
    failed_assert = None
    if failure.failed_assert is not None:
        diff = None
        if failure.failed_assert.diff is not None:
            diff = {
                "lines": list(failure.failed_assert.diff.lines),
                "cut_lines": failure.failed_assert.diff.cut_lines,
            }
        failed_assert = {
            "expression": failure.failed_assert.expression,
            "message": failure.failed_assert.message,
            "parts": [
                {
                    "source": part.source,
                    "depth": part.depth,
                    "evaluated": part.value is not None,
                    "value": _value(part.value) if part.value is not None else None,
                }
                for part in failure.failed_assert.parts
            ],
            "diff": diff,
        }

    return {
        "error_type": failure.error_type,
        "error_message": failure.error_message,
        "file": failure.file,
        "line": failure.line,
        "traceback": failure.traceback,
        "frames": [
            {"file": frame.file, "line": frame.line, "function": frame.function}
            for frame in failure.frames
        ],
        "assert": failed_assert,
        "locals": [
            {"name": local.name, "value": _value(local.value)}
            for local in failure.locals
        ],
        "stdout": _stream(failure.stdout),
        "stderr": _stream(failure.stderr),
        "rerun_command": failure.rerun_command,
    }


def _collection_error(failure: CollectionFailure) -> dict[str, Any]:
    return {
        "file": failure.file,
        "line": failure.line,
        "is_definition_error": failure.is_definition_error,
        "error_type": failure.error_type,
        "message": failure.message,
        "traceback": failure.traceback,
        "stdout": _stream(failure.stdout),
        "stderr": _stream(failure.stderr),
    }


def _value(value: PrintedValue) -> dict[str, Any]:
    return {
        "text": value.text,
        "cut_characters": value.cut_characters,
        "same_as": value.same_as,
    }


def _stream(stream: StreamOutput) -> dict[str, Any]:
    return {"text": stream.text, "cut_characters": stream.cut_characters}


class JsonReporter:
    """
    Prints nothing while the run goes, and the document when it is over.

    The document is all that is written to `out`.
    """

    def __init__(self, *, out: TextIO, list_passed: bool) -> None:
        self.out = out
        self.list_passed = list_passed

    def collected(self, count: int) -> None:
        pass

    def result(self, result: TestResult) -> None:
        pass

    def finished(self, report: RunReport) -> None:
        self.out.write(document_text(report, list_passed=self.list_passed))
        self.out.write("\n")
        self.out.flush()
