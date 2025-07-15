import click

from plain.cli import register_cli
from plain.observer.models import Trace


@register_cli("observer")
@click.group("observer")
def observer_cli():
    pass


@observer_cli.command()
@click.option("--force", is_flag=True, help="Skip confirmation prompt.")
def clear(force: bool):
    """Clear all observer data."""
    if not force:
        click.confirm(
            "Are you sure you want to clear all observer data? This cannot be undone.",
            abort=True,
        )

    print("Deleted", Trace.objects.all().delete())
