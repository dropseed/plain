"""
Test output: answers "what do I do next", not just "what happened".

Every failure block ends with the exact re-run command for that test.
"""

from __future__ import annotations

import click

from .runner import TestResult, TestRun

__all__ = ["Reporter"]

_STATUS_COLORS = {
    "passed": "green",
    "failed": "red",
    "skipped": "yellow",
}

_DOTS = {"passed": ".", "failed": "F", "skipped": "s"}


class Reporter:
    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose
        self._dots_on_line = 0

    def collected(self, count: int) -> None:
        click.secho(f"Collected {count} tests", dim=True)

    def result(self, result: TestResult) -> None:
        color = _STATUS_COLORS[result.outcome]
        bold = result.outcome == "failed"
        if self.verbose:
            status = result.outcome.upper()
            line = f"{status:<7} {result.test.id}"
            if result.outcome == "skipped" and result.skip_reason:
                line += f" ({result.skip_reason})"
            if result.outcome != "skipped":
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
            click.echo(_indent(result.traceback_text.rstrip()))
            click.echo()
            click.secho(f"Re-run: plain test {result.test.id}", dim=True)

    def summary(self, run: TestRun) -> None:
        parts = [f"{len(run.passed)} passed"]
        if run.failed:
            parts.append(f"{len(run.failed)} failed")
        if run.skipped:
            parts.append(f"{len(run.skipped)} skipped")
        line = f"{', '.join(parts)} in {run.duration:.2f}s"
        click.echo()
        click.secho(line, fg="red" if run.failed else "green", bold=True)


def _indent(text: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())
