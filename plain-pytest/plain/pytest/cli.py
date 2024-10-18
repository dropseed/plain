import os
import sys

import click
from dotenv import load_dotenv

import pytest


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
        load_dotenv(".env.test")

    returncode = pytest.main(list(pytest_args))
    if returncode:
        sys.exit(returncode)
