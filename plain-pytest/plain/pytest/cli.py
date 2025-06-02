import os
import sys

import click
from dotenv import load_dotenv

import pytest
from plain.cli import register_cli


@register_cli("test")
@click.command(
    context_settings={
        "ignore_unknown_options": True,
    }
)
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def cli(pytest_args):
    """Run tests with pytest"""

    if os.path.exists(".env.test"):
        click.secho("Loading environment variables from .env.test", fg="yellow")
        # plain.dev may load .env files first, so make sure we override any existing variables
        load_dotenv(".env.test", override=True)

    returncode = pytest.main(list(pytest_args))
    if returncode:
        sys.exit(returncode)
