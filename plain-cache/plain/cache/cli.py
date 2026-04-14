import click

from plain.cli import register_cli

from .models import CachedItem


@register_cli("cache")
@click.group()
def cli() -> None:
    """Cache management"""


@cli.command()
def clear_expired() -> None:
    """Clear expired cache entries"""
    click.echo("Clearing expired cache items...")
    count = CachedItem.query.expired().delete()
    click.echo(f"Deleted {count} expired cache items.")


@cli.command()
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def clear_all(yes: bool) -> None:
    """Clear all cache entries"""
    if not yes and not click.confirm(
        "Are you sure you want to delete all cache items?"
    ):
        return
    click.echo("Clearing all cache items...")
    count = CachedItem.query.all().delete()
    click.echo(f"Deleted {count} cache items.")


@cli.command()
def stats() -> None:
    """Show cache statistics"""
    total = CachedItem.query.count()
    expired = CachedItem.query.expired().count()
    unexpired = CachedItem.query.unexpired().count()
    forever = CachedItem.query.forever().count()

    click.echo(f"Total: {click.style(total, bold=True)}")
    click.echo(f"Expired: {click.style(expired, bold=True)}")
    click.echo(f"Unexpired: {click.style(unexpired, bold=True)}")
    click.echo(f"Forever: {click.style(forever, bold=True)}")
