import os
import subprocess
import sys
import tomllib
from importlib.util import find_spec
from pathlib import Path

import click

from plain.cli import register_cli
from plain.cli.print import print_event
from plain.cli.runtime import without_runtime_setup


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
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Git pre-commit checks"""
    # If no subcommand is provided, run the checks
    if ctx.invoked_subcommand is None:
        run_checks()


@cli.command()
@without_runtime_setup
def install() -> None:
    """Install the pre-commit git hook"""
    install_git_hook()


def run_checks() -> None:
    """Run all pre-commit checks"""

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
            print_event(f"Custom: {cmd}")
            result = subprocess.run(cmd, shell=True)
            if result.returncode != 0:
                sys.exit(result.returncode)

    # Run this first since it's probably the most likely to fail
    if find_spec("plain.code"):
        check_short("plain code check", "plain", "code", "check")

    if Path("uv.lock").exists():
        check_short("uv lock --check", "uv", "lock", "--check")

    if plain_db_connected():
        check_short("plain preflight", "plain", "preflight", "--quiet")
        check_short("plain migrate --check", "plain", "migrate", "--check")
        check_short(
            "plain makemigrations --dry-run --check",
            "plain",
            "makemigrations",
            "--dry-run",
            "--check",
        )
    else:
        check_short("plain preflight", "plain", "preflight", "--quiet")
        click.secho("--> Skipping migration checks", bold=True, fg="yellow")

    check_short("plain build", "plain", "build")

    if find_spec("plain.pytest"):
        print_event("plain test")
        result = subprocess.run(["plain", "test"])
        if result.returncode != 0:
            sys.exit(result.returncode)


def plain_db_connected() -> bool:
    result = subprocess.run(
        [
            "plain",
            "migrations",
            "list",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def check_short(message: str, *args: str) -> None:
    print_event(message, newline=False)
    env = {**os.environ, "FORCE_COLOR": "1"}
    result = subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env
    )
    if result.returncode != 0:
        click.secho("✘", fg="red")
        click.secho(result.stdout.decode("utf-8"))
        sys.exit(1)
    else:
        click.secho("✔", fg="green")
