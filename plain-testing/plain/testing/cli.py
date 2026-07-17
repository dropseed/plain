import os
import sys

import click

from plain.cli import register_cli
from plain.cli.runtime import common_command


@common_command
@register_cli("test")
@click.command(
    context_settings={
        "ignore_unknown_options": True,
    }
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cli(args: tuple[str, ...]) -> None:
    """Run tests"""
    # Re-exec into a fresh process so PLAIN_ENV=test is set before the
    # runtime loads settings (the `plain` CLI has already run setup() by the
    # time a subcommand dispatches).
    os.environ.setdefault("PLAIN_ENV", "test")
    os.execvp(sys.executable, [sys.executable, "-m", "plain.testing", *args])
