"""
Test output as text: answers "what do I do next", not just "what happened".

Every failure block ends with the exact re-run command for that test,
quoted so that pasting it into a shell runs that test and no other.

What is printed here is read from the same `RunReport` that `--json` prints
as a document. Nothing here works anything out about the run.
"""

import textwrap
from typing import TextIO

import click

from ..definition import TestDefinitionError
from .execution import RaisedWarning, TeardownError, TestResult
from .failure import (
    AssertedPart,
    CollectionFailure,
    Failure,
    LocalValue,
    format_collection_traceback,
)
from .output_capture import Output, StreamOutput
from .printing import FULL_VALUES_FLAG, PrintedValue
from .report import RunReport

__all__ = []

_STATUS_COLORS = {
    "passed": "green",
    "failed": "red",
    "skipped": "yellow",
}

# Takes the cursor back to the start of the line and clears the line: what
# the progress line is written over, and erased, with.
_START_OF_A_CLEARED_LINE = "\r\x1b[K"


def collection_error_text(cause: BaseException) -> str:
    """
    What to print for a file that couldn't be collected.

    A TestDefinitionError is printed as its message: it already says what is
    wrong and what to write instead. Anything else is an error in the test
    file like any other (a NameError, an ImportError), and is printed with
    the traceback that says where, starting at the test file.
    """
    if isinstance(cause, TestDefinitionError):
        return str(cause)
    return format_collection_traceback(cause)


def failure_text(failure: Failure) -> str:
    """
    What is printed for one failed test, under its `failed` line: where it
    failed, the assert with the values inside it, what differs, what else
    the test had in hand, and what it wrote.
    """
    sections = [failure.traceback.rstrip()]

    failed_assert = failure.failed_assert
    if failed_assert is not None:
        # The message the test gave is the traceback's last line, just
        # above.
        lines = [f"assert {failed_assert.expression}"]
        for part in failed_assert.parts:
            lines.extend(_part_lines(part))
        sections.append("\n".join(lines))

        diff = failed_assert.diff
        if diff is not None:
            lines = ["diff:", *(f"  {line}" for line in diff.lines)]
            if diff.cut_lines:
                lines.append(
                    f"  ... {diff.cut_lines:,} more lines"
                    f" ({FULL_VALUES_FLAG} prints them)"
                )
            sections.append("\n".join(lines))

    if failure.locals:
        lines = ["locals:"]
        for local in failure.locals:
            lines.extend(_local_lines(local))
        sections.append("\n".join(lines))

    sections.extend(
        output_sections(Output(stdout=failure.stdout, stderr=failure.stderr))
    )

    return "\n\n".join(sections)


def output_sections(output: Output) -> list[str]:
    """What was written to stdout and to stderr, each under its name."""
    sections = []
    for name, stream in (("stdout", output.stdout), ("stderr", output.stderr)):
        if stream.text:
            sections.append("\n".join(_stream_lines(name, stream)))
    return sections


def _stream_lines(name: str, stream: StreamOutput) -> list[str]:
    lines = [f"{name}:"]
    if stream.cut_characters:
        lines.append(
            f"  ... {stream.cut_characters:,} characters before this"
            f" ({FULL_VALUES_FLAG} prints them)"
        )
    lines.extend(f"  {line}" for line in stream.text.splitlines())
    return lines


def _part_lines(part: AssertedPart) -> list[str]:
    indent = "  " * (part.depth + 1)
    if part.value is None:
        return [f"{indent}{part.source}  (not evaluated)"]
    return _named_value_lines(part.source, part.value, indent=indent)


def _local_lines(local: LocalValue) -> list[str]:
    return _named_value_lines(local.name, local.value, indent="  ")


def _named_value_lines(name: str, value: PrintedValue, *, indent: str) -> list[str]:
    """
    `name = value` on one line, or the name and then a value of several
    lines under it. After a value the cap cut short, how much was cut.
    """
    if "\n" in value.text:
        lines = [f"{indent}{name} ="]
        lines.extend(f"{indent}  {line}" for line in value.text.splitlines())
    else:
        lines = [f"{indent}{name} = {value.text}"]
    if value.cut_characters:
        lines.append(
            f"{indent}  ... {value.cut_characters:,} more characters"
            f" ({FULL_VALUES_FLAG} prints them)"
        )
    return lines


class TextReporter:
    """
    Prints a run as it goes, and what came of it when it is over.

    `out` and `err` are where the runner's own output goes. While the run
    holds what tests write, they are not `sys.stdout` and `sys.stderr`.

    A test that passes prints nothing. With `verbose` each test prints a
    line as it finishes. With `progress`, which is for a terminal someone is
    watching, one line says how far the run has got: it is written over
    itself as tests finish and erased before the report, so nothing of it
    is left in what the run printed.
    """

    def __init__(
        self,
        *,
        out: TextIO,
        err: TextIO,
        verbose: bool = False,
        progress: bool = False,
    ) -> None:
        self.out = out
        self.err = err
        self.verbose = verbose
        self.progress = progress and not verbose
        self._collected = 0
        self._finished = 0
        self._failed = 0
        self._progress_is_shown = False

    def _print(
        self,
        text: str = "",
        *,
        newline: bool = True,
        fg: str | None = None,
        bold: bool = False,
        dim: bool = False,
    ) -> None:
        click.secho(text, file=self.out, nl=newline, fg=fg, bold=bold, dim=dim)

    def _print_error(self, text: str = "", *, fg: str | None = None) -> None:
        click.secho(text, file=self.err, fg=fg)

    def collected(self, count: int) -> None:
        plural = "" if count == 1 else "s"
        self._print(f"Collected {count} test{plural}", dim=True)
        self._collected = count

    def result(self, result: TestResult) -> None:
        self._finished += 1
        if result.outcome == "failed":
            self._failed += 1

        if self.verbose:
            # The outcome as `--json` spells it.
            line = f"{result.outcome:<7} {result.test.id}"
            if result.outcome == "skipped":
                line += f" ({result.skip_reason})"
            else:
                line += f" ({result.duration:.3f}s)"
            self._print(
                line,
                fg=_STATUS_COLORS[result.outcome],
                bold=result.outcome == "failed",
            )
        elif self.progress:
            self._show_progress()

    def _show_progress(self) -> None:
        line = f"{self._finished} of {self._collected}"
        if self._failed:
            line += f", {self._failed} failed"
        self.out.write(f"{_START_OF_A_CLEARED_LINE}{line}")
        self.out.flush()
        self._progress_is_shown = True

    def _erase_progress(self) -> None:
        if self._progress_is_shown:
            self.out.write(_START_OF_A_CLEARED_LINE)
            self.out.flush()
            self._progress_is_shown = False

    def _stopped(self, report: RunReport) -> None:
        """The run ended before any test was run."""
        stopped = report.stopped
        assert stopped is not None
        self._erase_progress()
        if stopped.reason == "no_tests_found":
            self._print(stopped.message, fg="yellow")
            return

        self._print_error(stopped.message, fg="red")
        if stopped.traceback is not None:
            self._print_error()
            self._print_error(textwrap.indent(stopped.traceback.rstrip(), "  "))
        for section in output_sections(stopped.output):
            self._print_error()
            self._print_error(textwrap.indent(section, "  "))

        # The lifecycles that had been set up were taken down again.
        if report.run is not None:
            for error in report.run.teardown_errors:
                self._print_error()
                self._print_error("teardown error", fg="red")
                self._print_error()
                self._print_error(textwrap.indent(_teardown_error_text(error), "  "))

        if stopped.reason == "setup_error":
            self._print_error()
            self._print_error("No test was run.", fg="red")

    def finished(self, report: RunReport) -> None:
        if report.stopped is not None:
            self._stopped(report)
            return

        run = report.run
        assert run is not None

        self._erase_progress()

        for result in run.failed:
            assert result.failure is not None
            self._print()
            self._print(f"failed {result.test.id}", fg="red", bold=True)
            self._print()
            self._print(textwrap.indent(failure_text(result.failure), "  "))
            self._print()
            self._print(f"Re-run: {result.failure.rerun_command}", dim=True)

        # Verbose output already gave each skipped test its own line.
        if run.skipped and not self.verbose:
            self._print()
            for result in run.skipped:
                self._print(
                    f"skipped {result.test.id} ({result.skip_reason})", fg="yellow"
                )

        # A definition error that is one paragraph is printed under its
        # heading with no lines left blank. Eighty files with the same
        # thing wrong are eighty of these, and every line is read.
        after_a_short_one = False
        for failure in report.collection_failures:
            text = _collection_failure_text(failure)
            is_short = failure.is_definition_error and "\n\n" not in text
            if not (is_short and after_a_short_one):
                self._print()
            self._print(f"collection error {failure.file}", fg="red", bold=True)
            if not is_short:
                self._print()
            self._print(textwrap.indent(text, "  "))
            after_a_short_one = is_short

        for error in run.teardown_errors:
            self._print()
            self._print("teardown error", fg="red", bold=True)
            self._print()
            self._print(textwrap.indent(_teardown_error_text(error), "  "))

        if run.interrupted is not None:
            self._print()
            self._print(f"interrupted {run.interrupted.test.id}", fg="red", bold=True)
            for section in output_sections(run.interrupted.output):
                self._print()
                self._print(textwrap.indent(section, "  "))

        if report.warnings:
            self._print()
            self._print("warnings", fg="yellow", bold=True)
            self._print()
            for warning in report.warnings:
                self._print(textwrap.indent(_warning_text(warning), "  "))

        if report.output:
            self._print()
            self._print("written outside any test", bold=True)
            for section in output_sections(report.output):
                self._print()
                self._print(textwrap.indent(section, "  "))

        self._summary(report)

    def _summary(self, report: RunReport) -> None:
        run = report.run
        assert run is not None
        counts = report.counts

        parts = [f"{counts.passed} passed"]
        if counts.failed:
            parts.append(f"{counts.failed} failed")
        if counts.skipped:
            parts.append(f"{counts.skipped} skipped")
        if counts.collection_errors:
            parts.append(f"{counts.collection_errors} collection errors")
        if counts.not_run:
            parts.append(f"{counts.not_run} not run")
        if counts.warnings:
            plural = "" if counts.warnings == 1 else "s"
            parts.append(f"{counts.warnings} warning{plural}")
        line = f"{', '.join(parts)} in {run.duration:.2f}s"
        if run.interrupted is not None:
            line = f"Interrupted: {line}"

        self._print()
        self._print(line, fg="green" if report.exit_code == 0 else "red", bold=True)


def _teardown_error_text(error: TeardownError) -> str:
    sections = [error.traceback.rstrip(), *output_sections(error.output)]
    return "\n\n".join(sections)


def _warning_text(warning: RaisedWarning) -> str:
    """The warning, and under it how often it was raised and where first."""
    times = "once" if warning.count == 1 else f"{warning.count:,} times"
    return (
        f"{warning.category}: {warning.message}\n"
        f"  raised {times}, first at {warning.file}:{warning.line}"
        f" in {warning.first_test}"
    )


def _collection_failure_text(failure: CollectionFailure) -> str:
    text = failure.message if failure.is_definition_error else failure.traceback
    assert text is not None
    sections = [
        text,
        *output_sections(Output(stdout=failure.stdout, stderr=failure.stderr)),
    ]
    return "\n\n".join(sections)
