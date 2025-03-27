import click

from plain.cli import register_cli

from .models import Session


@register_cli("sessions")
@click.group()
def cli():
    """Sessions management commands."""
    pass


@cli.command()
def clear_expired():
    Session.objects.clear_expired()
