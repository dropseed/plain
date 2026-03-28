from __future__ import annotations

import click

from ..convergence import detect_fixes
from ..db import get_connection


@click.command()
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
def converge(yes: bool) -> None:
    """Fix schema mismatches between models and the database.

    Detects and fixes:
    - Column type mismatches (e.g. character varying → text)
    - Missing or extra constraints (check, unique)
    - NOT VALID constraints needing validation

    Each fix is applied and committed independently so partial
    failures don't block subsequent fixes.
    """
    fixes = detect_fixes()

    if not fixes:
        click.secho("Schema is converged — nothing to fix.", fg="green")
        return

    click.secho(
        f"{len(fixes)} fix{'es' if len(fixes) != 1 else ''} to apply:\n", bold=True
    )
    for fix in fixes:
        click.echo(f"  {fix.describe()}")

    click.echo()

    if not yes:
        if not click.confirm("Apply these changes?"):
            return

    click.echo()

    applied = 0
    failed = 0
    conn = get_connection()

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

    click.echo()
    parts = []
    if applied:
        parts.append(f"{applied} applied")
    if failed:
        parts.append(f"{failed} failed")
    color = "green" if not failed else "yellow"
    click.secho(", ".join(parts) + ".", fg=color)
