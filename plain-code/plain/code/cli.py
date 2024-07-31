import subprocess
import sys
from pathlib import Path

import click
import tomllib

from plain.cli.print import print_event

DEFAULT_RUFF_CONFIG = Path(__file__).parent / "ruff_defaults.toml"


@click.group()
def cli():
    """Standard code formatting and linting."""
    pass


@cli.command()
@click.argument("path", default=".")
def check(path):
    """Check the given path for formatting or linting issues."""
    ruff_args = ["--config", str(DEFAULT_RUFF_CONFIG)]

    for e in get_code_config().get("exclude", []):
        ruff_args.extend(["--exclude", e])

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
@click.option("--unsafe-fixes", is_flag=True, help="Apply ruff unsafe fixes")
def fix(path, unsafe_fixes):
    """Lint and format the given path."""
    ruff_args = ["--config", str(DEFAULT_RUFF_CONFIG)]

    for e in get_code_config().get("exclude", []):
        ruff_args.extend(["--exclude", e])

    if unsafe_fixes:
        print_event("Ruff fix (with unsafe fixes)")
        result = subprocess.run(
            ["ruff", "check", path, "--fix", "--unsafe-fixes", *ruff_args]
        )
    else:
        print_event("Ruff fix")
        result = subprocess.run(["ruff", "check", path, "--fix", *ruff_args])

    if result.returncode != 0:
        sys.exit(result.returncode)

    print_event("Ruff format")
    result = subprocess.run(["ruff", "format", path, *ruff_args])

    if result.returncode != 0:
        sys.exit(result.returncode)


def get_code_config():
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return {}
    with pyproject.open("rb") as f:
        return tomllib.load(f).get("tool", {}).get("plain", {}).get("code", {})
