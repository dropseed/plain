import sys

import click

from plain.cli import register_cli

from .users.models import User


@register_cli("app")
@click.group()
def cli():
    """App related commands"""
    pass


@cli.command()
@click.argument("email")
def enable_admin_user(email):
    """Enable admin privileges for a user."""
    result = User.query.filter(email=email).update(is_admin=True)
    if result:
        click.echo(f"User {email} is now an admin.")
    else:
        click.echo(f"No user found with email {email}.")
        sys.exit(1)
