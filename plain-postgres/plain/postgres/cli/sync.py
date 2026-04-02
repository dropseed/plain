from __future__ import annotations

import sys

import click

from plain.runtime import settings

from ..convergence import execute_plan, plan_convergence


@click.command()
@click.option(
    "--check",
    is_flag=True,
    help="Exit with non-zero status if sync would make any database changes.",
)
def sync(check: bool) -> None:
    """Sync the database schema with models.

    In DEBUG mode: generates migrations, applies them, then converges constraints.
    In production: applies migrations, then converges constraints.

    Undeclared indexes and constraints are automatically dropped — models are
    the source of truth.
    """
    if check:
        _check()
        return

    if settings.DEBUG:
        _create_migrations()

    _migrate()
    _converge()


def _check() -> None:
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

    # Check for convergence
    plan = plan_convergence()
    if plan.has_work():
        has_changes = True
    if plan.blocked:
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
    from ..db import get_connection
    from ..migrations.executor import MigrationExecutor

    click.secho("Applying migrations...", bold=True)

    conn = get_connection()
    conn.ensure_connection()
    executor = MigrationExecutor(conn)
    targets = executor.loader.graph.leaf_nodes()
    migration_plan = executor.migration_plan(targets)

    if not migration_plan:
        click.echo("  No migrations to apply.")
        return

    click.echo(f"  Applying {len(migration_plan)} migration(s)...")
    executor.migrate(targets, plan=migration_plan)
    click.echo(f"  Applied {len(migration_plan)} migration(s).")


def _converge() -> None:
    click.secho("Converging schema...", bold=True)

    plan = plan_convergence()
    items = plan.executable()
    success = True

    if items:
        result = execute_plan(items)

        for r in result.results:
            if r.ok:
                click.echo(f"    {r.sql}")
            else:
                click.secho(f"    FAILED: {r.item.describe()} — {r.error}", fg="red")

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
        click.echo("  Schema is converged.")
