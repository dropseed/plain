import click

from plain.cli import register_cli

from .models import CachedItem


@register_cli("cache")
@click.group()
def cli() -> None:
    pass


@cli.command()
def clear_expired() -> None:
    click.echo("Clearing expired cache items...")
    result = CachedItem.query.expired().delete()
    click.echo(f"Deleted {result[0]} expired cache items.")


@cli.command()
@click.option("--force", is_flag=True)
def clear_all(force: bool) -> None:
    if not force and not click.confirm(
        "Are you sure you want to delete all cache items?"
    ):
        return
    click.echo("Clearing all cache items...")
    result = CachedItem.query.all().delete()
    click.echo(f"Deleted {result[0]} cache items.")


@cli.command()
def stats() -> None:
    total = CachedItem.query.count()
    expired = CachedItem.query.expired().count()
    unexpired = CachedItem.query.unexpired().count()
    forever = CachedItem.query.forever().count()

    click.echo(f"Total: {click.style(total, bold=True)}")
    click.echo(f"Expired: {click.style(expired, bold=True)}")
    click.echo(f"Unexpired: {click.style(unexpired, bold=True)}")
    click.echo(f"Forever: {click.style(forever, bold=True)}")
