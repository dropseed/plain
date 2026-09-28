import os
import sys
from pathlib import Path

import click

__all__ = []


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
def main(
    targets: tuple[str, ...],
    keyword: str | None,
    tags: tuple[str, ...],
    exclude_tags: tuple[str, ...],
    fail_fast: bool,
    verbose: bool,
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

    import plain.runtime

    from ..definition import TestDefinitionError
    from .collection import collect_tests
    from .execution import run_tests
    from .layout import find_tests_directory, import_helper_modules_from
    from .lifecycle_discovery import load_app_lifecycle, load_package_lifecycles
    from .reporting import Reporter

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

    reporter = Reporter(verbose=verbose)

    # Where this run's tests are is worked out here, once. Helper modules are
    # imported from the tests directory. A project with no tests directory
    # keeps them beside its test files, at the root.
    root = Path.cwd()
    tests_directory = find_tests_directory(root)
    has_tests_directory = tests_directory.is_dir()
    import_helper_modules_from(tests_directory if has_tests_directory else root)

    # The project's own lifecycle goes last, so it wraps closest to the test:
    # it enters with the packages' protection already in place (the database
    # transaction is open) and exits before theirs is taken down.
    try:
        app_lifecycle = load_app_lifecycle(root=root, tests_directory=tests_directory)
    except TestDefinitionError as e:
        reporter.lifecycle_error(e)
        raise SystemExit(2)
    if app_lifecycle is not None:
        lifecycles.append(app_lifecycle)

    try:
        tests, collection_errors = collect_tests(
            list(targets),
            root=root,
            exclude_dirs=exclude_dirs,
            helper_directory=tests_directory if has_tests_directory else None,
        )
    except FileNotFoundError as e:
        click.secho(str(e), fg="red", err=True)
        raise SystemExit(2)

    if keyword:
        tests = [t for t in tests if keyword in t.id]
    if tags:
        tests = [t for t in tests if any(tag in t.tags for tag in tags)]
    if exclude_tags:
        tests = [t for t in tests if not any(tag in t.tags for tag in exclude_tags)]

    if not tests and not collection_errors:
        click.secho("No tests found", fg="yellow")
        raise SystemExit(5)

    reporter.collected(len(tests))

    run = run_tests(
        tests,
        lifecycles=lifecycles,
        fail_fast=fail_fast,
        on_result=reporter.result,
    )

    reporter.failures(run)
    reporter.skips(run)
    reporter.collection_errors(collection_errors)
    reporter.summary(run, collection_error_count=len(collection_errors))

    sys.exit(0 if run.ok and not collection_errors else 1)
