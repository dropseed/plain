"""
Test output: answers "what do I do next", not just "what happened".

Every failure block ends with the exact re-run command for that test,
quoted so that pasting it into a shell runs that test and no other.
"""

import ast
import shlex
import textwrap
import traceback
from pathlib import Path

import click

from ..definition import TestDefinitionError
from .collection import CollectionError
from .execution import TestResult, TestRun

__all__ = []

_STATUS_COLORS = {
    "passed": "green",
    "failed": "red",
    "skipped": "yellow",
}

_DOTS = {"passed": ".", "failed": "F", "skipped": "s"}

_RUNNER_DIRECTORY = str(Path(__file__).parent)


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

    # The frames above the test file are the runner loading it, by way of
    # `ast` or the import system. A SyntaxError has no frames below those:
    # it names the file and the line itself.
    not_the_test_file = (_RUNNER_DIRECTORY, ast.__file__, "<frozen importlib")
    tb = cause.__traceback__
    while tb is not None:
        if not tb.tb_frame.f_code.co_filename.startswith(not_the_test_file):
            break
        tb = tb.tb_next
    return "".join(traceback.format_exception(type(cause), cause, tb)).rstrip()


def rerun_command(test_id: str) -> str:
    """
    The command that runs one test, safe to paste. A case id can hold
    anything (`test_price[annual plan]`), and a shell reads spaces, brackets,
    quotes and `$` for itself unless the id is quoted.
    """
    return f"plain test {shlex.quote(test_id)}"


class Reporter:
    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose
        self._dots_on_line = 0

    def collected(self, count: int) -> None:
        plural = "" if count == 1 else "s"
        click.secho(f"Collected {count} test{plural}", dim=True)

    def result(self, result: TestResult) -> None:
        color = _STATUS_COLORS[result.outcome]
        bold = result.outcome == "failed"
        if self.verbose:
            status = result.outcome.upper()
            line = f"{status:<7} {result.test.id}"
            if result.outcome == "skipped":
                line += f" ({result.skip_reason})"
            else:
                line += f" ({result.duration:.3f}s)"
            click.secho(line, fg=color, bold=bold)
        else:
            click.secho(_DOTS[result.outcome], nl=False, fg=color, bold=bold)
            self._dots_on_line += 1
            if self._dots_on_line >= 80:
                click.echo()
                self._dots_on_line = 0

    def failures(self, run: TestRun) -> None:
        if not self.verbose and self._dots_on_line:
            click.echo()
        for result in run.failed:
            click.echo()
            click.secho(f"FAILED {result.test.id}", fg="red", bold=True)
            click.echo()
            click.echo(textwrap.indent(result.traceback_text.rstrip(), "  "))
            click.echo()
            click.secho(f"Re-run: {rerun_command(result.test.id)}", dim=True)

    def skips(self, run: TestRun) -> None:
        # Verbose output already gave each skipped test its own line.
        if self.verbose or not run.skipped:
            return
        click.echo()
        for result in run.skipped:
            click.secho(f"SKIPPED {result.test.id} ({result.skip_reason})", fg="yellow")

    def lifecycle_error(self, error: TestDefinitionError) -> None:
        """The project's lifecycle can't be used, so nothing is going to run."""
        click.secho(str(error), fg="red", err=True)
        if error.__cause__ is not None:
            click.echo(err=True)
            click.echo(
                textwrap.indent(collection_error_text(error.__cause__), "  "),
                err=True,
            )

    def collection_errors(self, errors: list[CollectionError]) -> None:
        for error in errors:
            click.echo()
            click.secho(f"COLLECTION ERROR {error.path}", fg="red", bold=True)
            click.echo()
            click.echo(textwrap.indent(collection_error_text(error.error), "  "))

    def summary(self, run: TestRun, *, collection_error_count: int = 0) -> None:
        parts = [f"{len(run.passed)} passed"]
        if run.failed:
            parts.append(f"{len(run.failed)} failed")
        if run.skipped:
            parts.append(f"{len(run.skipped)} skipped")
        if collection_error_count:
            parts.append(f"{collection_error_count} collection errors")
        line = f"{', '.join(parts)} in {run.duration:.2f}s"
        failed = run.failed or collection_error_count
        click.echo()
        click.secho(line, fg="red" if failed else "green", bold=True)
