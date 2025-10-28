import os
import subprocess
import sys
import tomllib
from importlib.util import find_spec
from pathlib import Path

import click

from plain.cli import register_cli
from plain.cli.print import print_event


def install_git_hook() -> None:
    hook_path = os.path.join(".git", "hooks", "pre-commit")
    if os.path.exists(hook_path):
        print("pre-commit hook already exists")
    else:
        with open(hook_path, "w") as f:
            f.write(
                """#!/bin/sh
plain pre-commit"""
            )
        os.chmod(hook_path, 0o755)
        print("pre-commit hook installed")


@register_cli("pre-commit")
@click.command()
@click.option("--install", is_flag=True)
def cli(install: bool) -> None:
    """Git pre-commit checks"""
    if install:
        install_git_hook()
        return

    pyproject = Path("pyproject.toml")

    if pyproject.exists():
        with open(pyproject, "rb") as f:
            pyproject = tomllib.load(f)
        for name, data in (
            pyproject.get("tool", {})
            .get("plain", {})
            .get("pre-commit", {})
            .get("run", {})
        ).items():
            cmd = data["cmd"]
            print_event(
                click.style(f"Custom[{name}]:", bold=True)
                + click.style(f" {cmd}", dim=True),
                newline=False,
            )
            result = subprocess.run(cmd, shell=True)
            if result.returncode != 0:
                sys.exit(result.returncode)

    # Run this first since it's probably the most likely to fail
    if find_spec("plain.code"):
        check_short(
            click.style("Code:", bold=True)
            + click.style(" plain code check", dim=True),
            "plain",
            "code",
            "check",
        )

    if Path("uv.lock").exists():
        check_short(
            click.style("Dependencies:", bold=True)
            + click.style(" uv lock --check", dim=True),
            "uv",
            "lock",
            "--check",
        )

    if plain_db_connected():
        check_short(
            click.style("Preflight:", bold=True)
            + click.style(" plain preflight", dim=True),
            "plain",
            "preflight",
            "--quiet",
        )
        check_short(
            click.style("Migrate:", bold=True)
            + click.style(" plain migrate --check", dim=True),
            "plain",
            "migrate",
            "--check",
        )
        check_short(
            click.style("Migrations:", bold=True)
            + click.style(" plain makemigrations --dry-run --check", dim=True),
            "plain",
            "makemigrations",
            "--dry-run",
            "--check",
        )
    else:
        check_short(
            click.style("Preflight:", bold=True)
            + click.style(" plain preflight", dim=True),
            "plain",
            "preflight",
            "--quiet",
        )
        click.secho("--> Skipping migration checks", bold=True, fg="yellow")

    check_short(
        click.style("Build:", bold=True) + click.style(" plain build", dim=True),
        "plain",
        "build",
    )

    if find_spec("plain.pytest"):
        print_event(
            click.style("Test:", bold=True) + click.style(" plain test", dim=True)
        )
        result = subprocess.run(["plain", "test"])
        if result.returncode != 0:
            sys.exit(result.returncode)


def plain_db_connected() -> bool:
    result = subprocess.run(
        [
            "plain",
            "models",
            "show-migrations",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def check_short(message: str, *args: str) -> None:
    print_event(message, newline=False)
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        click.secho("✘", fg="red")
        click.secho(result.stdout.decode("utf-8"))
        sys.exit(1)
    else:
        click.secho("✔", fg="green")
