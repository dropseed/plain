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
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def cli(pytest_args: tuple[str, ...]) -> None:
    """Test suite with pytest"""
    # .env.test loading is handled by the pytest plugin in plugin.py

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *pytest_args,
    ]

    # Replace current process with pytest
    os.execvp(cmd[0], cmd)
