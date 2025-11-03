import logging
import sys

import click

logger = logging.getLogger("plain.chores")


@click.group()
def chores() -> None:
    """Routine maintenance tasks"""
    pass


@chores.command("list")
@click.option(
    "--name", default=None, type=str, help="Name of the chore to run", multiple=True
)
def list_chores(name: tuple[str, ...]) -> None:
    """List all registered chores"""
    from plain.chores.registry import chores_registry

    chores_registry.import_modules()

    chore_classes = chores_registry.get_chores()

    if name:
        chore_classes = [
            chore_class
            for chore_class in chore_classes
            if f"{chore_class.__module__}.{chore_class.__qualname__}" in name
        ]

    for chore_class in chore_classes:
        chore_name = f"{chore_class.__module__}.{chore_class.__qualname__}"
        click.secho(f"{chore_name}", bold=True, nl=False)
        description = chore_class.__doc__.strip() if chore_class.__doc__ else ""
        if description:
            click.secho(f": {description}", dim=True)
        else:
            click.echo("")


@chores.command("run")
@click.option(
    "--name", default=None, type=str, help="Name of the chore to run", multiple=True
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be done without executing"
)
def run_chores(name: tuple[str, ...], dry_run: bool) -> None:
    """Run specified chores"""
    from plain.chores.registry import chores_registry

    chores_registry.import_modules()

    chore_classes = chores_registry.get_chores()

    if name:
        chore_classes = [
            chore_class
            for chore_class in chore_classes
            if f"{chore_class.__module__}.{chore_class.__qualname__}" in name
        ]

    chores_failed = []

    for chore_class in chore_classes:
        chore_name = f"{chore_class.__module__}.{chore_class.__qualname__}"
        click.echo(f"{chore_name}:", nl=False)
        if dry_run:
            click.secho(" (dry run)", fg="yellow", nl=False)
        else:
            try:
                chore = chore_class()
                result = chore.run()
            except Exception:
                click.secho(" Failed", fg="red")
                chores_failed.append(chore_class)
                logger.exception(f"Error running chore {chore_name}")
                continue

            if result is None:
                click.secho(" Done", fg="green")
            else:
                click.secho(f" {result}", fg="green")

    if chores_failed:
        sys.exit(1)
