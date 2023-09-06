import os
import subprocess
from pathlib import Path

import click

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from bolt.runtime import settings


@click.command("format")  # format is a keyword
@click.option("--check", is_flag=True, help="Check formatting instead of fixing")
@click.argument("paths", nargs=-1)
def cli(check, paths):
    """Format Python code with black and ruff"""

    if not paths:
        if Path("pyproject.toml").exists():
            with open("pyproject.toml", "rb") as f:
                pyproject = tomllib.load(f)
            paths = (
                pyproject.get("tool", {})
                .get("bolt", {})
                .get("format", {})
                .get("paths", paths)
            )

    if not paths:
        # Make relative for nicer output
        paths = [os.path.relpath(settings.APP_PATH)]

    if check:
        fmt_check(paths)
    else:
        fmt(paths)


def fmt(paths):
    # If we're fixing, we do ruff first so black can re-format any ruff fixes
    print_event(f"Fixing {', '.join(paths)} with ruff")
    subprocess.check_call(
        [
            "ruff",
            "--fix-only",
            "--exit-zero",
            *paths,
        ]
    )

    print_event(f"Formatting {', '.join(paths)} with black")
    subprocess.check_call(
        [
            "black",
            *paths,
        ]
    )


def fmt_check(paths):
    print_event(f"Checking {', '.join(paths)} with black")
    subprocess.check_call(["black", "--check", *paths])

    print_event(f"Checking {', '.join(paths)} with ruff")
    subprocess.check_call(["ruff", *paths])


def print_event(msg, newline=True):
    arrow = click.style("-->", fg=214, bold=True)
    if not newline:
        message += " "
    click.secho(f"{arrow} {msg}", nl=newline)
