import click

from .docs import docs
from .md import md
from .request import request


@click.group("agent", invoke_without_command=True)
@click.pass_context
def agent(ctx: click.Context) -> None:
    """Tools for coding agents."""
    if ctx.invoked_subcommand is None:
        # If no subcommand provided, show all AGENTS.md files
        ctx.invoke(md, show_all=True, show_list=False, package="")


# Add commands to the group
agent.add_command(docs)
agent.add_command(md)
agent.add_command(request)
