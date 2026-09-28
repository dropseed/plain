import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import click

if TYPE_CHECKING:
    from .execution import TestResult
    from .output_capture import OutputCapture
    from .report import Command, RunReport

__all__ = []


class Reporter(Protocol):
    """What a run tells as it goes: the text reporter, or the JSON one."""

    def collected(self, count: int) -> None: ...

    def result(self, result: TestResult) -> None: ...

    def finished(self, report: RunReport) -> None: ...


@click.command()
@click.argument("targets", nargs=-1)
@click.option(
    "-k",
    "keyword",
    metavar="TEXT",
    default=None,
    help="Run only tests whose id contains TEXT",
)
@click.option(
    "--tag",
    "tags",
    metavar="NAME",
    multiple=True,
    help="Run only tests tagged NAME (repeat for any of several)",
)
@click.option(
    "--exclude-tag",
    "exclude_tags",
    metavar="NAME",
    multiple=True,
    help="Leave out tests tagged NAME (repeatable)",
)
@click.option("-x", "--fail-fast", is_flag=True, help="Stop at the first failure")
@click.option("-v", "--verbose", is_flag=True, help="Print one line per test")
@click.option(
    "--full-values",
    is_flag=True,
    help="Print every value and all the output in a failure, however long",
)
@click.option(
    "-s",
    "--show-output",
    is_flag=True,
    help="Let what tests print and log through as they write it",
)
def main(
    targets: tuple[str, ...],
    keyword: str | None,
    tags: tuple[str, ...],
    exclude_tags: tuple[str, ...],
    fail_fast: bool,
    verbose: bool,
    full_values: bool,
    show_output: bool,
) -> None:
    """Run tests

    With no TARGETS, runs every test in every `test_*.py` file under the
    directory the command runs from. A target narrows that to a directory, a
    file, or one test, and a path is relative to the same directory.

    \b
      tests/accounts                                a directory
      tests/test_signup.py                          a file
      tests/test_signup.py::test_welcome            a test
      tests/test_signup.py::TestInvites             a class
      tests/test_signup.py::TestInvites::test_sent  a test in a class
      'tests/test_price.py::test_total[annual]'     one case of a test

    Quote a target that names a case. A failure prints the command that
    runs it again, already quoted.

    What a test prints or logs is held while it runs. A test that fails has
    it printed with its failure, and a test that passes has it thrown away.
    """
    # Tests run with PLAIN_ENV=test. The runner reads no `.env` files itself:
    # plain.dev does, for every command, from the hook it registers with
    # `plain.runtime.setup()`. With this set first, that hook picks
    # `.env.test*` and skips `.env.local`, so a run doesn't depend on what
    # one machine has in it.
    os.environ.setdefault("PLAIN_ENV", "test")
    # Marks the process as a test run for code that behaves differently under
    # one — CLI color, for instance, which would otherwise add escape codes to
    # output a test is asserting on.
    os.environ["PLAIN_TEST_RUNNING"] = "1"

    from .output_capture import OutputCapture
    from .report import Command
    from .reporting import TextReporter

    command = Command(
        directory=str(Path.cwd()),
        targets=targets,
        keyword=keyword,
        tags=tags,
        exclude_tags=exclude_tags,
        fail_fast=fail_fast,
        full_values=full_values,
    )

    # Held from here, before the app is set up: setting it up writes too.
    with OutputCapture(show_output=show_output, full_output=full_values) as capture:
        reporter = TextReporter(
            out=capture.real_stdout, err=capture.real_stderr, verbose=verbose
        )
        report = _run(command, capture=capture, reporter=reporter)
        reporter.finished(report)

    sys.exit(report.exit_code)


def _run(command: Command, *, capture: OutputCapture, reporter: Reporter) -> RunReport:
    import plain.runtime

    from ..definition import TestDefinitionError
    from .collection import collect_tests
    from .execution import run_tests
    from .failure import describe_collection_error, shown_path
    from .layout import find_tests_directory, import_helper_modules_from
    from .lifecycle_discovery import load_app_lifecycle, load_package_lifecycles
    from .report import RunReport, StoppedRun
    from .reporting import collection_error_text

    def stopped(
        reason: str, message: str, *, traceback: str | None = None
    ) -> RunReport:
        return RunReport(
            command=command,
            run=None,
            stopped=StoppedRun(
                reason=reason,
                message=message,
                traceback=traceback,
                output=capture.take(),
            ),
            collection_failures=(),
            selected=0,
        )

    # App mode: a resolvable Plain app gets the packages' lifecycles. Library
    # mode: no app, kernel only — collection, assertions, and runner still
    # work. The runtime is the authority on whether there's an app.
    try:
        plain.runtime.setup()
    except plain.runtime.AppPathNotFound:
        lifecycles = []
        exclude_dirs: tuple[str, ...] = ()
    else:
        lifecycles = load_package_lifecycles()
        # The Plain `app` directory isn't a place tests live — a convention
        # the runner knows, not the collection kernel.
        exclude_dirs = ("app",)

    # Where this run's tests are is worked out here, once. Helper modules are
    # imported from the tests directory. A project with no tests directory
    # keeps them beside its test files, at the root.
    root = Path(command.directory)
    tests_directory = find_tests_directory(root)
    has_tests_directory = tests_directory.is_dir()
    import_helper_modules_from(tests_directory if has_tests_directory else root)

    # The project's own lifecycle goes last, so it wraps closest to the test:
    # it enters with the packages' protection already in place (the database
    # transaction is open) and exits before theirs is taken down.
    try:
        app_lifecycle = load_app_lifecycle(root=root, tests_directory=tests_directory)
    except TestDefinitionError as e:
        cause = e.__cause__
        return stopped(
            "lifecycle_error",
            str(e),
            traceback=collection_error_text(cause) if cause is not None else None,
        )
    if app_lifecycle is not None:
        lifecycles.append(app_lifecycle)

    try:
        tests, collection_errors = collect_tests(
            list(command.targets),
            root=root,
            exclude_dirs=exclude_dirs,
            helper_directory=tests_directory if has_tests_directory else None,
            capture=capture,
        )
    except FileNotFoundError as e:
        return stopped("target_not_found", str(e))

    if command.keyword:
        tests = [t for t in tests if command.keyword in t.id]
    if command.tags:
        tests = [t for t in tests if any(tag in t.tags for tag in command.tags)]
    if command.exclude_tags:
        tests = [
            t for t in tests if not any(tag in t.tags for tag in command.exclude_tags)
        ]

    if not tests and not collection_errors:
        return stopped("no_tests_found", "No tests found")

    # What setting up and collecting wrote was the run's. Each file that
    # couldn't be collected has kept what loading it wrote.
    capture.discard()

    reporter.collected(len(tests))

    run = run_tests(
        tests,
        lifecycles=lifecycles,
        fail_fast=command.fail_fast,
        full_values=command.full_values,
        on_result=reporter.result,
        capture=capture,
    )

    return RunReport(
        command=command,
        run=run,
        stopped=None,
        collection_failures=tuple(
            describe_collection_error(
                error, file=shown_path(str(error.path)), output=error.output
            )
            for error in collection_errors
        ),
        selected=len(tests),
    )
