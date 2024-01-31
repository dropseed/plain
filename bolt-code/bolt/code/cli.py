import re
import subprocess
import sys
from pathlib import Path

import click

from bolt.cli.print import print_event

DEFAULT_RUFF_CONFIG = Path(__file__).parent / "ruff_defaults.toml"


@click.group()
def cli():
    """Standard code formatting and linting."""
    pass


@cli.command()
@click.argument("path", default=".")
def check(path):
    """Check the given path for formatting or linting issues."""
    ruff_args = []

    if not user_has_ruff_config():
        click.secho("Using default bolt.code ruff config", italic=True)
        ruff_args.extend(["--config", str(DEFAULT_RUFF_CONFIG)])

    print_event("Ruff check")
    result = subprocess.run(["ruff", "check", path, *ruff_args])

    if result.returncode != 0:
        sys.exit(result.returncode)

    print_event("Ruff format check")
    result = subprocess.run(["ruff", "format", path, "--check", *ruff_args])

    if result.returncode != 0:
        sys.exit(result.returncode)


@cli.command()
@click.argument("path", default=".")
def fix(path):
    """Lint and format the given path."""
    ruff_args = []

    if not user_has_ruff_config():
        click.secho("Using default bolt.code ruff config", italic=True)
        ruff_args.extend(["--config", str(DEFAULT_RUFF_CONFIG)])

    print_event("Ruff check")
    result = subprocess.run(["ruff", "check", path, "--fix", *ruff_args])

    if result.returncode != 0:
        sys.exit(result.returncode)

    print_event("Ruff format")
    result = subprocess.run(["ruff", "format", path, *ruff_args])

    if result.returncode != 0:
        sys.exit(result.returncode)


def user_has_ruff_config():
    try:
        output = subprocess.check_output(["ruff", "check", ".", "--show-settings"])
    except subprocess.CalledProcessError:
        return False

    if re.search("Settings path: (.+)", output.decode("utf-8")):
        return True
    else:
        return False
