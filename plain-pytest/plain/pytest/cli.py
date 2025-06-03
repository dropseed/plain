import os
import subprocess
import sys

import click
from dotenv import load_dotenv

from plain.cli import register_cli


@register_cli("test")
@click.command(
    context_settings={
        "ignore_unknown_options": True,
    }
)
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
def cli(pytest_args):
    """Run pytest with .env.test loaded"""

    if os.path.exists(".env.test"):
        click.secho("Loading environment variables from .env.test", fg="yellow")
        # plain.dev may load .env files first, so make sure we override any existing variables
        load_dotenv(".env.test", override=True)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
    ] + list(pytest_args)

    result = subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)

    if returncode := result.returncode:
        sys.exit(returncode)
