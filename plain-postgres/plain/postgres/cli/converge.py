from __future__ import annotations

import sys

import click

from ..convergence import execute_plan, plan_convergence
from .decorators import (
    cli_schema_lock,
    cli_wait_for_database,
    database_management_command,
)


@click.command()
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt.",
)
@database_management_command
def converge(yes: bool) -> None:
    """Fix schema mismatches between models and the database.

    Detects and fixes:
    - Missing indexes (using CONCURRENTLY)
    - Missing constraints (check, unique)
    - NOT VALID constraints needing validation
    - Undeclared indexes and constraints (dropped automatically)

    Each fix is applied and committed independently so partial
    failures don't block subsequent fixes.
    """
    cli_wait_for_database()

    plan = plan_convergence()
    items = plan.executable()
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

        with cli_schema_lock():
            # Re-plan under the lock — another converge or sync may have
            # already applied (or changed) these fixes while we waited.
            confirmed = {item.describe() for item in items}
            plan = plan_convergence()
            items = plan.executable()

            new_items = [item for item in items if item.describe() not in confirmed]
            if new_items and not yes:
                # The plan grew while we waited at the prompt or for the
                # lock — don't execute work the operator never approved.
                click.secho(
                    "The schema changed while waiting — new fixes not in the confirmed plan:",
                    fg="red",
                    bold=True,
                )
                for item in new_items:
                    click.secho(f"  {item.describe()}", fg="red")
                raise click.ClickException("Re-run to review the updated plan.")

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

    if not success:
        sys.exit(1)
    elif not items:
        click.secho("Schema is converged — nothing to fix.", fg="green")
