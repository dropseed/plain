import click
from .db import cli as db_cli


@click.group()
def cli():
    """Local development commands (db)"""
    pass


cli.add_command(db_cli)
