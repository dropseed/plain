from __future__ import annotations

import click

from plain.runtime import settings

from ..convergence import detect_fixes
from ..db import get_connection


@click.command()
@click.option(
    "--backup/--no-backup",
    "backup",
    is_flag=True,
    default=None,
    help="Explicitly enable/disable pre-migration backups.",
)
def sync(backup: bool | None) -> None:
    """Sync the database schema with models.

    In DEBUG mode: generates migrations, applies them, then converges constraints.
    In production: applies migrations, then converges constraints.
    """
    if settings.DEBUG:
        _create_migrations()

    _migrate(backup=backup)
    _converge()


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


def _migrate(*, backup: bool | None) -> None:
    from .migrations import apply

    click.secho("Applying migrations...", bold=True)
    apply.callback(
        package_label=None,
        migration_name=None,
        fake=False,
        plan=False,
        check_unapplied=False,
        backup=backup,
        no_input=False,
        atomic_batch=None,
        quiet=False,
    )


def _converge() -> None:
    click.secho("Converging schema...", bold=True)

    fixes = detect_fixes()
    if not fixes:
        click.secho("Schema is converged.", fg="green")
        return

    conn = get_connection()
    applied = 0
    failed = 0

    for fix in fixes:
        try:
            with conn.cursor() as cursor:
                sql = fix.apply(cursor)
            conn.commit()
            click.echo(f"  {sql}")
            applied += 1
        except Exception as e:
            conn.rollback()
            click.secho(f"  FAILED: {fix.describe()} — {e}", fg="red")
            failed += 1

    parts = []
    if applied:
        parts.append(f"{applied} applied")
    if failed:
        parts.append(f"{failed} failed")
    color = "green" if not failed else "yellow"
    click.secho(", ".join(parts) + ".", fg=color)
