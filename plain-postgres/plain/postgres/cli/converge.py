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

    conn = get_connection()
    with conn.cursor() as cursor:
        for fix in fixes:
            sql = fix.apply(cursor)
            click.echo(f"  {sql}")

    conn.commit()

    click.echo()
    click.secho(
        f"Applied {len(fixes)} fix{'es' if len(fixes) != 1 else ''}.", fg="green"
    )
