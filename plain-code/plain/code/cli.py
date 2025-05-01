import subprocess
import sys
import tomllib
from pathlib import Path

import click

from plain.cli import register_cli
from plain.cli.print import print_event

from .biome import Biome

DEFAULT_RUFF_CONFIG = Path(__file__).parent / "ruff_defaults.toml"


@register_cli("code")
@click.group()
def cli():
    """Code formatting and linting"""
    pass


@cli.command()
@click.pass_context
def install(ctx):
    """Install or update the Biome standalone per configuration."""
    if version := get_code_config().get("biome", {}).get("version", ""):
        biome = Biome()
        click.secho(
            f"Installing Biome standalone version {version}...", bold=True, nl=False
        )
        installed = biome.install(version)
        click.secho(f"Biome {installed} installed", fg="green")
    else:
        ctx.invoke(update)


@cli.command()
def update():
    """Update the Biome standalone binary to the latest release."""
    biome = Biome()
    click.secho("Updating Biome standalone...", bold=True)
    version = biome.install()
    click.secho(f"Biome {version} installed", fg="green")


@cli.command()
@click.pass_context
@click.argument("path", default=".")
def check(ctx, path):
    """Check the given path for formatting or linting issues."""
    ruff_args = ["--config", str(DEFAULT_RUFF_CONFIG)]
    config = get_code_config()

    for e in config.get("exclude", []):
        ruff_args.extend(["--exclude", e])

    print_event("Ruff check")
    result = subprocess.run(["ruff", "check", path, *ruff_args])
    if result.returncode != 0:
        sys.exit(result.returncode)

    print_event("Ruff format check")
    result = subprocess.run(["ruff", "format", path, "--check", *ruff_args])
    if result.returncode != 0:
        sys.exit(result.returncode)

    if config.get("biome", {}).get("enabled", True):
        biome = Biome()

        if biome.needs_update():
            ctx.invoke(install)

        print_event("Biome check")
        result = biome.invoke("check", path)
        if result.returncode != 0:
            sys.exit(result.returncode)


@register_cli("fix")
@cli.command()
@click.pass_context
@click.argument("path", default=".")
@click.option("--unsafe-fixes", is_flag=True, help="Apply ruff unsafe fixes")
@click.option("--add-noqa", is_flag=True, help="Add noqa comments to suppress errors")
def fix(ctx, path, unsafe_fixes, add_noqa):
    """Lint and format the given path."""
    ruff_args = ["--config", str(DEFAULT_RUFF_CONFIG)]
    config = get_code_config()

    for e in config.get("exclude", []):
        ruff_args.extend(["--exclude", e])

    if unsafe_fixes and add_noqa:
        print("Cannot use both --unsafe-fixes and --add-noqa")
        sys.exit(1)

    if unsafe_fixes:
        print_event("Ruff fix (with unsafe fixes)")
        result = subprocess.run(
            ["ruff", "check", path, "--fix", "--unsafe-fixes", *ruff_args]
        )
    elif add_noqa:
        print_event("Ruff fix (add noqa)")
        result = subprocess.run(["ruff", "check", path, "--add-noqa", *ruff_args])
    else:
        print_event("Ruff fix")
        result = subprocess.run(["ruff", "check", path, "--fix", *ruff_args])

    if result.returncode != 0:
        sys.exit(result.returncode)

    print_event("Ruff format")
    result = subprocess.run(["ruff", "format", path, *ruff_args])
    if result.returncode != 0:
        sys.exit(result.returncode)

    if config.get("biome", {}).get("enabled", True):
        biome = Biome()

        if biome.needs_update():
            ctx.invoke(install)

        print_event("Biome format")

        args = ["check", path, "--write"]

        if unsafe_fixes:
            args.append("--unsafe")

        result = biome.invoke(*args)

        if result.returncode != 0:
            sys.exit(result.returncode)


def get_code_config():
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return {}
    with pyproject.open("rb") as f:
        return tomllib.load(f).get("tool", {}).get("plain", {}).get("code", {})
