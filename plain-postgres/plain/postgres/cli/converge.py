from __future__ import annotations

import sys

import click

from ..convergence import execute_plan, plan_convergence


@click.command()
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@click.option(
    "--drop-undeclared",
    is_flag=True,
    help="Drop indexes and constraints not declared on any model.",
)
def converge(yes: bool, drop_undeclared: bool) -> None:
    """Fix schema mismatches between models and the database.

    Detects and fixes:
    - Missing indexes (using CONCURRENTLY)
    - Missing constraints (check, unique)
    - NOT VALID constraints needing validation

    With --drop-undeclared, also drops indexes and constraints that exist in the
    database but are not declared on any model.

    Without --drop-undeclared, exits non-zero if undeclared constraints remain
    (constraints affect database behavior). Undeclared indexes are reported but
    do not block success.

    Each fix is applied and committed independently so partial
    failures don't block subsequent fixes.
    """
    plan = plan_convergence()
    items = plan.executable(drop_undeclared=drop_undeclared)
    success = True

    if items:
        click.secho(
            f"{len(items)} fix{'es' if len(items) != 1 else ''} to apply:\n",
            bold=True,
        )
        for item in items:
            click.echo(f"  {item.describe()}")

        click.echo()

        if not yes:
            if not click.confirm("Apply these changes?"):
                return

        click.echo()

        result = execute_plan(items)

        for r in result.results:
            if r.ok:
                click.echo(f"  {r.sql}")
            else:
                click.secho(f"  FAILED: {r.item.describe()} — {r.error}", fg="red")

        click.echo()
        click.secho(f"  {result.summary}", fg="green" if result.ok else "yellow")
        if not result.ok_for_sync:
            success = False

    if plan.blocked:
        click.echo()
        click.secho("  Schema changes require a staged rollout:", fg="red", bold=True)
        for item in plan.blocked:
            click.secho(f"    {item.drift.describe()}", fg="red")
            if item.guidance:
                click.secho(f"      {item.guidance}", fg="red", dim=True)
        success = False

    if not drop_undeclared and plan.blocking_cleanup:
        click.echo()
        click.secho("  Undeclared constraints still in database:", fg="red", bold=True)
        for item in plan.blocking_cleanup:
            click.secho(f"    {item.describe()}", fg="red")
        click.secho("  Rerun with --drop-undeclared to remove them.", fg="red")
        success = False

    if not drop_undeclared and plan.optional_cleanup:
        click.echo()
        for item in plan.optional_cleanup:
            click.echo(f"    {item.describe()}")
        click.echo("  Run with --drop-undeclared to remove undeclared indexes.")

    if not success:
        sys.exit(1)
    elif not items:
        click.secho("Schema is converged — nothing to fix.", fg="green")
