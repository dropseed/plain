from __future__ import annotations

import sys

import click

from plain.runtime import settings

from ..convergence import detect_fixes


@click.command()
@click.option(
    "--check",
    is_flag=True,
    help="Exit with non-zero status if sync would make any database changes.",
)
@click.option(
    "--prune",
    is_flag=True,
    help="Also drop indexes and constraints not declared on any model.",
)
def sync(check: bool, prune: bool) -> None:
    """Sync the database schema with models.

    In DEBUG mode: generates migrations, applies them, then converges constraints.
    In production: applies migrations, then converges constraints.

    With --prune, also drops indexes and constraints that exist in the
    database but are not declared on any model.
    """
    if check:
        _check(prune=prune)
        return

    if settings.DEBUG:
        _create_migrations()

    _migrate()
    _converge(prune=prune)


def _check(*, prune: bool) -> None:
    """Exit non-zero if sync would make any database changes."""
    from .migrations import apply, create

    has_changes = False

    # Check if migrations would be created (DEBUG only)
    if settings.DEBUG:
        try:
            create.callback(
                package_labels=(),
                dry_run=False,
                empty=False,
                no_input=True,
                name=None,
                check=True,
                verbosity=0,
            )
        except SystemExit:
            has_changes = True

    # Check for unapplied migrations
    try:
        apply.callback(
            package_label=None,
            migration_name=None,
            fake=False,
            plan=False,
            check_unapplied=True,
            no_input=True,
            atomic_batch=None,
            quiet=True,
        )
    except SystemExit:
        has_changes = True

    # Check for convergence fixes
    if detect_fixes(include_prunable=prune):
        has_changes = True

    if has_changes:
        sys.exit(1)


def _create_migrations() -> None:
    from .migrations import create

    click.secho("Checking for model changes...", bold=True)
    create.callback(
        package_labels=(),
        dry_run=False,
        empty=False,
        no_input=False,
        name=None,
        check=False,
        verbosity=1,
    )


def _migrate() -> None:
    from .migrations import apply

    click.secho("Applying migrations...", bold=True)
    apply.callback(
        package_label=None,
        migration_name=None,
        fake=False,
        plan=False,
        check_unapplied=False,
        no_input=False,
        atomic_batch=None,
        quiet=False,
    )


def _converge(*, prune: bool) -> None:
    click.secho("Converging schema...", bold=True)

    fixes = detect_fixes(include_prunable=prune)
    if not fixes:
        click.secho("Schema is converged.", fg="green")
        return

    applied = 0
    failed = 0

    for fix in fixes:
        try:
            sql = fix.apply()
            click.echo(f"  {sql}")
            applied += 1
        except Exception as e:
            click.secho(f"  FAILED: {fix.describe()} — {e}", fg="red")
            failed += 1

    parts = []
    if applied:
        parts.append(f"{applied} applied")
    if failed:
        parts.append(f"{failed} failed")
    color = "green" if not failed else "yellow"
    click.secho(", ".join(parts) + ".", fg=color)
