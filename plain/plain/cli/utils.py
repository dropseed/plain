import click

from plain.utils.crypto import get_random_string


@click.group()
def utils():
    pass


@utils.command()
def generate_secret_key():
    """Generate a new secret key"""
    new_secret_key = get_random_string(50)
    click.echo(new_secret_key)
