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
@click.option(
    "--drop-undeclared",
    is_flag=True,
    help="Drop indexes and constraints not declared on any model.",
)
def sync(check: bool, drop_undeclared: bool) -> None:
    """Sync the database schema with models.

    In DEBUG mode: generates migrations, applies them, then converges constraints.
    In production: applies migrations, then converges constraints.

    With --drop-undeclared, also drops indexes and constraints that exist in the
    database but are not declared on any model.

    Without --drop-undeclared, exits non-zero if undeclared constraints remain
    (constraints affect database behavior). Undeclared indexes are reported but
    do not block success.
    """
    if check:
        _check(drop_undeclared=drop_undeclared)
        return

    if settings.DEBUG:
        _create_migrations()

    _migrate()
    _converge(drop_undeclared=drop_undeclared)


def _check(*, drop_undeclared: bool) -> None:
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
    if plan.has_work(drop_undeclared=drop_undeclared):
        has_changes = True
    if not drop_undeclared and plan.blocking_cleanup:
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


def _converge(*, drop_undeclared: bool) -> None:
    click.secho("Converging schema...", bold=True)

    plan = plan_convergence()
    items = plan.executable(drop_undeclared=drop_undeclared)
    success = True

    if items:
        result = execute_plan(items)

        for r in result.results:
            if r.ok:
                click.echo(f"  {r.sql}")
            else:
                click.secho(f"  FAILED: {r.item.describe()} — {r.error}", fg="red")

        click.secho(result.summary, fg="green" if result.ok else "yellow")
        if not result.ok_for_sync:
            success = False

    if plan.blocked:
        click.echo()
        click.secho("Schema changes require a staged rollout:", fg="red", bold=True)
        for item in plan.blocked:
            click.secho(f"  {item.drift.describe()}", fg="red")
            if item.guidance:
                click.secho(f"    {item.guidance}", fg="red", dim=True)
        success = False

    if not drop_undeclared and plan.blocking_cleanup:
        click.echo()
        click.secho("Undeclared constraints still in database:", fg="red", bold=True)
        for item in plan.blocking_cleanup:
            click.secho(f"  {item.describe()}", fg="red")
        click.secho("Rerun with --drop-undeclared to remove them.", fg="red")
        success = False

    if not drop_undeclared and plan.optional_cleanup:
        click.echo()
        for item in plan.optional_cleanup:
            click.echo(f"  {item.describe()}")
        click.echo("Run with --drop-undeclared to remove undeclared indexes.")

    if not success:
        sys.exit(1)
    elif not items:
        click.secho("Schema is converged.", fg="green")
