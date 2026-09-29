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
    "--match",
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
@click.option("--fail-fast", is_flag=True, help="Stop at the first failure")
@click.option(
    "--verbose",
    is_flag=True,
    help="Print one line per test (not with --json)",
)
@click.option(
    "--full-values",
    is_flag=True,
    help="Print every value and all the output in a failure, however long",
)
@click.option(
    "--show-output",
    is_flag=True,
    help="Let what tests print and log through as they write it (not with --json)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the run as one JSON document, when it is over",
)
@click.option(
    "--list-passed",
    is_flag=True,
    help="With --json, list the tests that passed too",
)
def main(
    targets: tuple[str, ...],
    match: str | None,
    tags: tuple[str, ...],
    exclude_tags: tuple[str, ...],
    fail_fast: bool,
    verbose: bool,
    full_values: bool,
    show_output: bool,
    as_json: bool,
    list_passed: bool,
) -> None:
    """Run tests

    With no TARGETS, runs every test in every `test_*.py` file under the
    directory the command runs from. A target narrows that to a directory, a
    file, or one test, and a path is relative to the same directory.

    \b
      tests/accounts                                a directory
      tests/test_signup.py                          a file
      tests/test_signup.py::test_welcome            a test
      tests/test_signup.py:42                       the test line 42 is in
      'tests/test_price.py::test_total[annual]'     one case of a test

    Quote a target that names a case. A failure prints the command that
    runs it again, already quoted.

    What a test prints or logs is held while it runs. A test that fails has
    it printed with its failure, and a test that passes has it thrown away.

    With --json nothing is printed until the run is over, and then one
    document is: what was asked for, what ran, and for each failure
    everything the text report would have said, as data.

    \b
    Exits with:
      0    every test that ran passed
      1    a test failed, or a file couldn't be collected
      2    the command can't be used as given
      3    setting up failed, so no test was run
      4    no tests matched
      130  stopped with Ctrl-C
    """
    if as_json and verbose:
        raise click.UsageError(
            "--json prints one document when the run is over, and --verbose"
            " has nothing to add to it. Pass --list-passed to have every test"
            " in the document."
        )
    if as_json and show_output:
        raise click.UsageError(
            "--json writes one document to stdout and nothing else, so it"
            " can't let output through with --show-output. A failure in the"
            " document carries what its test wrote."
        )
    if list_passed and not as_json:
        raise click.UsageError(
            "--list-passed says what goes in the --json document. For a line"
            " per test as they run, pass --verbose."
        )

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

    from .json_report import JsonReporter
    from .output_capture import OutputCapture
    from .report import Command
    from .reporting import TextReporter

    command = Command(
        argv=tuple(sys.argv),
        directory=str(Path.cwd()),
        targets=targets,
        match=match,
        tags=tags,
        exclude_tags=exclude_tags,
        fail_fast=fail_fast,
        full_values=full_values,
    )

    # Held from here, before the app is set up: setting it up writes too.
    with OutputCapture(show_output=show_output, full_output=full_values) as capture:
        reporter: Reporter
        if as_json:
            reporter = JsonReporter(out=capture.real_stdout, list_passed=list_passed)
        else:
            reporter = TextReporter(
                out=capture.real_stdout,
                err=capture.real_stderr,
                verbose=verbose,
                # For someone watching a terminal. What is let through with
                # --show-output is written where a line of progress would
                # be, so there is none then.
                progress=capture.real_stdout.isatty() and not show_output,
            )
        report = _run(command, capture=capture, reporter=reporter)
        reporter.finished(report)

    sys.exit(report.exit_code)


def _run(command: Command, *, capture: OutputCapture, reporter: Reporter) -> RunReport:
    import plain.runtime

    from ..definition import TestDefinitionError
    from .collection import collect_tests
    from .execution import TestRun, run_tests
    from .failure import describe_collection_error, format_traceback, shown_path
    from .layout import find_tests_directory, import_helper_modules_from
    from .lifecycle_discovery import load_app_lifecycle, load_package_lifecycles
    from .output_capture import joined
    from .report import RunReport, StoppedRun
    from .reporting import collection_error_text
    from .targets import TargetError

    # What is written outside any test and any file being collected, a
    # piece at a time as the run gets on.
    outside_tests = []

    def stopped(
        reason: str,
        message: str,
        *,
        traceback: str | None = None,
        run: TestRun | None = None,
    ) -> RunReport:
        outside_tests.append(capture.take())
        return RunReport(
            command=command,
            run=run,
            stopped=StoppedRun(
                reason=reason,
                message=message,
                traceback=traceback,
                output=joined(outside_tests),
            ),
            collection_failures=(),
            selected=0,
        )

    def could_not_set_up(what: str, error: BaseException) -> RunReport:
        if isinstance(error, SystemExit):
            message = f"{what} exited, with {error.code!r}."
        else:
            message = f"{what} raised {type(error).__qualname__}: {error}"
        return stopped("setup_error", message, traceback=format_traceback(error))

    try:
        # App mode: a resolvable Plain app gets the packages' lifecycles.
        # Library mode: no app, kernel only — collection, assertions, and
        # runner still work. The runtime is the authority on whether there's
        # an app.
        try:
            plain.runtime.setup()
        except plain.runtime.AppPathNotFound:
            lifecycles = []
            application_directory = None
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            return could_not_set_up("Setting up the app", error)
        else:
            try:
                lifecycles = load_package_lifecycles()
            except KeyboardInterrupt:
                raise
            except BaseException as error:
                return could_not_set_up("Loading the packages' test lifecycles", error)
            # Tests aren't kept in the application: it is what is imported
            # as `app` and what gets deployed. Collection leaves its test
            # files out and says that it did.
            application_directory = plain.runtime.APP_PATH

        # Where this run's tests are is worked out here, once. Helper modules
        # are imported from the tests directory. A project with no tests
        # directory keeps them beside its test files, at the root.
        root = Path(command.directory)
        tests_directory = find_tests_directory(root)
        has_tests_directory = tests_directory.is_dir()
        import_helper_modules_from(tests_directory if has_tests_directory else root)

        # The project's own lifecycle goes last, so it wraps closest to the
        # test: it enters with the packages' protection already in place (the
        # database transaction is open) and exits before theirs is taken
        # down.
        try:
            app_lifecycle = load_app_lifecycle(
                root=root, tests_directory=tests_directory
            )
        except TestDefinitionError as e:
            cause = e.__cause__
            return stopped(
                "lifecycle_error",
                str(e),
                traceback=collection_error_text(cause) if cause is not None else None,
            )
        if app_lifecycle is not None:
            lifecycles.append(app_lifecycle)

        # What setting up wrote is the run's. From here to the first test,
        # what is written is a file being loaded, and is kept by that file
        # if it can't be collected.
        outside_tests.append(capture.take())

        try:
            tests, collection_errors = collect_tests(
                list(command.targets),
                root=root,
                application_directory=application_directory,
                helper_directory=tests_directory if has_tests_directory else None,
                capture=capture,
            )
        except TargetError as e:
            return stopped("target_not_found", str(e))

        if command.match:
            tests = [t for t in tests if command.match in t.id]
        if command.tags:
            tests = [t for t in tests if any(tag in t.tags for tag in command.tags)]
        if command.exclude_tags:
            tests = [
                t
                for t in tests
                if not any(tag in t.tags for tag in command.exclude_tags)
            ]

        if not tests and not collection_errors:
            return stopped("no_tests_found", "No tests found")

        # Each file that couldn't be collected has kept what loading it
        # wrote. What is left was written between them.
        outside_tests.append(capture.take())

        reporter.collected(len(tests))

        run = run_tests(
            tests,
            lifecycles=lifecycles,
            fail_fast=command.fail_fast,
            full_values=command.full_values,
            on_result=reporter.result,
            capture=capture,
        )
    except KeyboardInterrupt:
        # Stopped before the first test, or while the lifecycles were being
        # taken down. A test that was running when it was stopped is in the
        # run, which reports it.
        return stopped("interrupted", "Interrupted before any test was run.")

    outside_tests.extend([run.setup_output, run.teardown_output])

    failed_setup = run.setup_failure
    if failed_setup is not None:
        return stopped(
            "setup_error",
            f"{failed_setup.lifecycle}.setup_worker() "
            + (
                f"exited, with {failed_setup.error_message}."
                if failed_setup.error_type == "SystemExit"
                else f"raised {failed_setup.error_type}: {failed_setup.error_message}"
            ),
            traceback=failed_setup.traceback,
            run=run,
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
        output=joined(outside_tests),
    )
