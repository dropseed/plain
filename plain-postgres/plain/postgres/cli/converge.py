from __future__ import annotations

import click

from ..convergence import execute_fixes, plan_convergence


@click.command()
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@click.option(
    "--prune",
    is_flag=True,
    help="Also drop indexes and constraints not declared on any model.",
)
def converge(yes: bool, prune: bool) -> None:
    """Fix schema mismatches between models and the database.

    Detects and fixes:
    - Missing indexes (using CONCURRENTLY)
    - Missing constraints (check, unique)
    - NOT VALID constraints needing validation

    With --prune, also drops indexes and constraints that exist in the
    database but are not declared on any model.

    Each fix is applied and committed independently so partial
    failures don't block subsequent fixes.
    """
    plan = plan_convergence()
    fixes = plan.executable(prune=prune)

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

    result = execute_fixes(fixes)

    for r in result.results:
        if r.ok:
            click.echo(f"  {r.sql}")
        else:
            click.secho(f"  FAILED: {r.fix.describe()} — {r.error}", fg="red")

    click.echo()
    click.secho(result.summary, fg="green" if result.ok else "yellow")
