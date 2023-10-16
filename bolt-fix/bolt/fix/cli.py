import os
import subprocess
import sys
from pathlib import Path

import click

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from bolt.runtime import APP_PATH

RUFF_DEFAULTS = [
    "--ignore",
    ",".join(
        [
            "E501",  # Line length
            "S101",  # pytest use of assert
        ]
    ),
    "--select",
    ",".join(
        [
            "E",
            "F",
            "I",  # isort
            # "C90",  # mccabe
            # "N",  # pep8-naming
            "UP",  # pyupgrade
            # "S",  # bandit
            # "B",  # bugbear
            "C4",  # flake8-comprehensions
            # "DTZ",  # flake8-datetimez
            "ISC",  # flake8-implicit-str-concat
            # "G",  # flake8-logging-format
            # "T20",  # print
            "PT",  # pytest
        ]
    ),
    "--target-version",
    "py310",  # Bolt targets at least 3.10 and up
]

BLACK_DEFAULTS = [
    "--target-version",
    "py310",  # Bolt targets at least 3.10 and up
]


@click.command("fix")
@click.option(
    "--check", "do_check", is_flag=True, help="Check formatting instead of fixing"
)
@click.argument("paths", nargs=-1)
def cli(do_check, paths):
    """Check and fix Python code with black and ruff"""

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
        paths = [os.path.relpath(APP_PATH)]

    if do_check:
        returncode = check(paths)
    else:
        returncode = fix(paths)

    if returncode:
        sys.exit(returncode)


def fix(paths):
    # If we're fixing, we do ruff first so black can re-format any ruff fixes
    print_event(f"Fixing {', '.join(paths)} with ruff")
    ruff_result = subprocess.run(
        [
            "ruff",
            "--fix",
            # "--exit-zero",
            *RUFF_DEFAULTS,
            *paths,
        ]
    )

    print_event(f"Fixing {', '.join(paths)} with black")
    black_result = subprocess.run(
        [
            "black",
            *BLACK_DEFAULTS,
            *paths,
        ]
    )

    return ruff_result.returncode or black_result.returncode


def check(paths):
    print_event(f"Checking {', '.join(paths)} with black")
    black_result = subprocess.run(["black", "--check", *BLACK_DEFAULTS, *paths])

    print_event(f"Checking {', '.join(paths)} with ruff")
    ruff_result = subprocess.run(["ruff", *RUFF_DEFAULTS, *paths])

    return ruff_result.returncode or black_result.returncode


def print_event(msg, newline=True):
    arrow = click.style("-->", fg=214, bold=True)
    if not newline:
        msg += " "
    click.secho(f"{arrow} {msg}", nl=newline)
