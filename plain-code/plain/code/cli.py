from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import click

from plain.cli import register_cli
from plain.cli.print import print_event
from plain.cli.runtime import common_command, without_runtime_setup

from .biome import Biome

DEFAULT_RUFF_CONFIG = Path(__file__).parent / "ruff_defaults.toml"


@without_runtime_setup
@register_cli("code")
@click.group()
def cli() -> None:
    """Code formatting and linting"""
    pass


@without_runtime_setup
@cli.command()
@click.option("--force", is_flag=True, help="Reinstall even if up to date")
@click.pass_context
def install(ctx: click.Context, force: bool) -> None:
    """Install or update Biome binary"""
    config = get_code_config()

    if not config.get("biome", {}).get("enabled", True):
        click.secho("Biome is disabled in configuration", fg="yellow")
        return

    biome = Biome()

    if force or not biome.is_installed() or biome.needs_update():
        version_to_install = config.get("biome", {}).get("version", "")
        if version_to_install:
            click.secho(
                f"Installing Biome standalone version {version_to_install}...",
                bold=True,
                nl=False,
            )
            installed = biome.install(version_to_install)
            click.secho(f"Biome {installed} installed", fg="green")
        else:
            ctx.invoke(update)
    else:
        click.secho("Biome already installed", fg="green")


@without_runtime_setup
@cli.command()
def update() -> None:
    """Update Biome to latest version"""
    config = get_code_config()

    if not config.get("biome", {}).get("enabled", True):
        click.secho("Biome is disabled in configuration", fg="yellow")
        return

    biome = Biome()
    click.secho("Updating Biome standalone...", bold=True)
    version = biome.install()
    click.secho(f"Biome {version} installed", fg="green")


@without_runtime_setup
@cli.command()
@click.pass_context
@click.argument("path", default=".")
def check(ctx: click.Context, path: str) -> None:
    """Check for formatting and linting issues"""
    ruff_args = ["--config", str(DEFAULT_RUFF_CONFIG)]
    config = get_code_config()

    for e in config.get("exclude", []):
        ruff_args.extend(["--exclude", e])

    def maybe_exit(return_code: int) -> None:
        if return_code != 0:
            click.secho(
                "\nCode check failed. Run `plain fix` and/or fix issues manually.",
                fg="red",
                err=True,
            )
            sys.exit(return_code)

    print_event(
        click.style("Ruff lint:", bold=True) + click.style(" ruff check", dim=True)
    )
    result = subprocess.run(["ruff", "check", path, *ruff_args])
    maybe_exit(result.returncode)

    print_event(
        click.style("Ruff format:", bold=True)
        + click.style(" ruff format --check", dim=True)
    )
    result = subprocess.run(["ruff", "format", path, "--check", *ruff_args])
    maybe_exit(result.returncode)

    if config.get("biome", {}).get("enabled", True):
        biome = Biome()

        if biome.needs_update():
            ctx.invoke(install)

        print_event(
            click.style("Biome:", bold=True) + click.style(" biome check", dim=True)
        )
        result = biome.invoke("check", path)
        maybe_exit(result.returncode)


@common_command
@without_runtime_setup
@register_cli("fix", shortcut_for="code fix")
@cli.command()
@click.pass_context
@click.argument("path", default=".")
@click.option("--unsafe-fixes", is_flag=True, help="Apply ruff unsafe fixes")
@click.option("--add-noqa", is_flag=True, help="Add noqa comments to suppress errors")
def fix(ctx: click.Context, path: str, unsafe_fixes: bool, add_noqa: bool) -> None:
    """Fix formatting and linting issues"""
    ruff_args = ["--config", str(DEFAULT_RUFF_CONFIG)]
    config = get_code_config()

    for e in config.get("exclude", []):
        ruff_args.extend(["--exclude", e])

    if unsafe_fixes and add_noqa:
        raise click.UsageError("Cannot use both --unsafe-fixes and --add-noqa")

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


def get_code_config() -> dict[str, Any]:
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return {}
    with pyproject.open("rb") as f:
        return tomllib.load(f).get("tool", {}).get("plain", {}).get("code", {})
