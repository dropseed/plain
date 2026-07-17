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

    from .collection import CollectionError, collect_tests
    from .lifecycles import load_lifecycles
    from .reporting import Reporter
    from .runner import run_tests

    # App mode: a resolvable Plain app gets the full lifecycle. Library mode:
    # no app, kernel only — collection, assertions, and runner still work.
    app_mode = (Path.cwd() / "app").exists() or os.environ.get("PLAIN_SETTINGS_MODULE")
    if app_mode:
        import plain.runtime

        plain.runtime.setup()
        lifecycles = load_lifecycles()
    else:
        lifecycles = []

    reporter = Reporter(verbose=verbose)

    try:
        tests = collect_tests(list(targets))
    except CollectionError as e:
        click.secho(f"Collection error in {e.path}:", fg="red", bold=True, err=True)
        click.echo(f"  {e.error!r}", err=True)
        raise SystemExit(2)
    except FileNotFoundError as e:
        click.secho(str(e), fg="red", err=True)
        raise SystemExit(2)

    if keyword:
        tests = [t for t in tests if keyword in t.id]
    if tags:
        tests = [t for t in tests if any(tag in t.tags for tag in tags)]
    if exclude_tags:
        tests = [t for t in tests if not any(tag in t.tags for tag in exclude_tags)]

    if not tests:
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
    reporter.summary(run)

    sys.exit(0 if run.ok else 1)


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
