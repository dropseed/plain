import click

from plain.cli import register_cli

from .core import Importmap


@register_cli("importmap")
@click.group()
def cli():
    pass


@cli.command()
def generate():
    """Generate importmap.lock"""
    importmap = Importmap()
    importmap.load()
