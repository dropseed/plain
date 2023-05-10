import click

from .core import Importmap


@click.group()
def cli():
    pass


@cli.command()
def generate():
    """Generate importmap.lock"""
    importmap = Importmap()
    importmap.load()
