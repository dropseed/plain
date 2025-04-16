import logging
import sys

import click

logger = logging.getLogger("plain.chores")


@click.group()
def chores():
    """Routine maintenance tasks"""
    pass


@chores.command("list")
@click.option("--group", default=None, type=str, help="Group to run", multiple=True)
@click.option(
    "--name", default=None, type=str, help="Name of the chore to run", multiple=True
)
def list_chores(group, name):
    """
    List all registered chores.
    """
    from plain.chores.registry import chores_registry

    chores_registry.import_modules()

    if group or name:
        chores = [
            chore
            for chore in chores_registry.get_chores()
            if (chore.group in group or not group) and (chore.name in name or not name)
        ]
    else:
        chores = chores_registry.get_chores()

    for chore in chores:
        click.secho(f"{chore}", bold=True, nl=False)
        if chore.description:
            click.echo(f": {chore.description}")
        else:
            click.echo("")


@chores.command("run")
@click.option("--group", default=None, type=str, help="Group to run", multiple=True)
@click.option(
    "--name", default=None, type=str, help="Name of the chore to run", multiple=True
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be done without executing"
)
def run_chores(group, name, dry_run):
    """
    Run the specified chores.
    """
    from plain.chores.registry import chores_registry

    chores_registry.import_modules()

    if group or name:
        chores = [
            chore
            for chore in chores_registry.get_chores()
            if (chore.group in group or not group) and (chore.name in name or not name)
        ]
    else:
        chores = chores_registry.get_chores()

    chores_failed = []

    for chore in chores:
        click.echo(f"{chore.name}:", nl=False)
        if dry_run:
            click.echo(" (dry run)", fg="yellow")
        else:
            try:
                result = chore.run()
            except Exception:
                click.secho(" Failed", fg="red")
                chores_failed.append(chore)
                logger.exception(f"Error running chore {chore.name}")
                continue

            if result is None:
                click.secho(" Done", fg="green")
            else:
                click.secho(f" {result}", fg="green")

    if chores_failed:
        sys.exit(1)
