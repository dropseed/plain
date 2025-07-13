import click

from plain.cli import register_cli
from plain.observe.models import Trace


@register_cli("observe")
@click.group("observe")
def observe_cli():
    pass


@observe_cli.command()
@click.option("--force", is_flag=True, help="Force clear all observability data.")
def clear(force: bool):
    """Clear all observability data."""
    if not force:
        click.confirm(
            "Are you sure you want to clear all observability data? This cannot be undone.",
            abort=True,
        )

    print("Deleted", Trace.objects.all().delete())
