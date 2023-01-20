import os

import click
from forgecore import Forge


@click.command("format")  # format is a keyword
@click.option("--check", is_flag=True, help="Check formatting instead of fixing")
@click.argument("files", nargs=-1)
def cli(check, files):
    """Format Python code with black and ruff"""
    if not files:
        # Make relative for nicer output
        files = [os.path.relpath(Forge().project_dir)]

    if check:
        fmt_check(files)
    else:
        fmt(files)


def fmt(files):
    forge = Forge()

    # If we're fixing, we do ruff first so black can re-format any ruff fixes
    click.secho(f"Fixing {', '.join(files)} with ruff", bold=True)

    forge.venv_cmd(
        "ruff",
        "--fix-only",
        *files,
        check=True,
    )

    click.echo()

    click.secho(f"Formatting {', '.join(files)} with black", bold=True)

    forge.venv_cmd(
        "black",
        *files,
        check=True,
    )


def fmt_check(files):
    forge = Forge()

    click.secho(f"Checking {', '.join(files)} with black", bold=True)
    forge.venv_cmd("black", "--check", *files, check=True)
    click.echo()

    click.secho(f"Checking {', '.join(files)} with ruff", bold=True)
    forge.venv_cmd("ruff", *files, check=True)
    click.echo()
