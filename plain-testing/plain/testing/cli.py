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
    # Re-exec into a fresh process so the runner owns the setup decision (app
    # vs library mode) instead of inheriting this process's already-completed
    # setup, and so the run starts from clean interpreter state.
    os.environ.setdefault("PLAIN_ENV", "test")
    os.execvp(sys.executable, [sys.executable, "-m", "plain.testing", *args])
