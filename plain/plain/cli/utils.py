import click
from plain.utils.crypto import get_random_string

from .runtime import without_runtime_setup


@without_runtime_setup
@click.group()
def utils() -> None:
    """Utility commands"""


@utils.command()
def generate_secret_key() -> None:
    """Generate a new secret key"""
    new_secret_key = get_random_string(50)
    click.echo(new_secret_key)
