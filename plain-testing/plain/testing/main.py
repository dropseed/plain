from __future__ import annotations

import os
import sys
from pathlib import Path

import click


@click.command()
@click.argument("targets", nargs=-1)
@click.option("-k", "keyword", default=None, help="Filter tests by id substring")
@click.option("--tag", "tags", multiple=True, help="Run only tests with this tag")
@click.option(
    "--exclude-tag", "exclude_tags", multiple=True, help="Skip tests with this tag"
)
@click.option("-x", "--fail-fast", is_flag=True, help="Stop on first failure")
@click.option("-v", "--verbose", is_flag=True, help="One line per test")
def main(
    targets: tuple[str, ...],
    keyword: str | None,
    tags: tuple[str, ...],
    exclude_tags: tuple[str, ...],
    fail_fast: bool,
    verbose: bool,
) -> None:
    """Run tests"""
    # Tests run with PLAIN_ENV=test so the dotenv ladder picks `.env.test*`
    # and skips `.env.local` for determinism.
    os.environ.setdefault("PLAIN_ENV", "test")
    _load_dotenv()

    import plain.runtime

    from .collection import collect_tests
    from .lifecycles import load_lifecycles
    from .reporting import Reporter
    from .runner import run_tests

    # App mode: a resolvable Plain app gets the full lifecycle. Library mode:
    # no app, kernel only — collection, assertions, and runner still work.
    # The runtime is the authority on whether there's an app.
    try:
        plain.runtime.setup()
    except plain.runtime.AppPathNotFound:
        lifecycles = []
        exclude_dirs: tuple[str, ...] = ()
    else:
        lifecycles = load_lifecycles()
        # The Plain `app` directory isn't a place tests live — a convention
        # the runner knows, not the collection kernel.
        exclude_dirs = ("app",)

    reporter = Reporter(verbose=verbose)

    try:
        tests, collection_errors = collect_tests(
            list(targets), exclude_dirs=exclude_dirs
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
    reporter.collection_errors(collection_errors)
    reporter.summary(run, collection_error_count=len(collection_errors))

    sys.exit(0 if run.ok and not collection_errors else 1)


def _load_dotenv() -> None:
    """
    Load `.env.test*` files. Prefer plain.dev's loader (the full precedence
    ladder); fall back to a minimal `.env.test` parse so tests behave the
    same in environments without plain.dev installed.
    """
    try:
        from plain.dev.dotenv import load_dotenv_files
    except ModuleNotFoundError:
        _load_dotenv_file(Path.cwd() / ".env.test")
    else:
        load_dotenv_files()


def _load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))
