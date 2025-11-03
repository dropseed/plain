import click

from .docs import docs
from .md import md
from .request import request


@click.group("agent")
def agent() -> None:
    """Tools for coding agents"""
    pass


# Add commands to the group
agent.add_command(docs)
agent.add_command(md)
agent.add_command(request)
