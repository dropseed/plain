import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import click


def install_git_hook():
    hook_path = os.path.join(".git", "hooks", "pre-commit")
    if os.path.exists(hook_path):
        print("pre-commit hook already exists")
    else:
        with open(hook_path, "w") as f:
            f.write(
                """#!/bin/sh
bolt pre-commit"""
            )
        os.chmod(hook_path, 0o755)
        print("pre-commit hook installed")


@click.command()
@click.option("--install", is_flag=True)
def cli(install):
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
            .get("bolt", {})
            .get("pre-commit", {})
            .get("run", {})
        ).items():
            cmd = data["cmd"]
            print_event(f"Custom: {name}")
            result = subprocess.run(cmd, shell=True)
            if result.returncode != 0:
                sys.exit(result.returncode)

    check_short("Checking .env files for changes", "bolt", "env", "check")

    if Path("poetry.lock").exists():
        check_short("Checking poetry.lock", "poetry", "lock", "--check")

    if find_spec("ruff"):
        check_short("Running ruff", "ruff", "check", ".")
        check_short("Running ruff format check", "ruff", "format", "--check", ".")
    elif find_spec("black"):
        check_short("Running black", "black", "--check", ".")

    if bolt_db_connected():
        check_short(
            "Running preflight checks",
            "bolt",
            "preflight",
            "--database",
            "default",
        )
        check_short("Checking Bolt migrations", "bolt", "legacy", "migrate", "--check")
        check_short(
            "Checking for Bolt models missing migrations",
            "bolt",
            "legacy",
            "makemigrations",
            "--dry-run",
            "--check",
        )
    else:
        check_short("Running Bolt checks (without database)", "bolt", "preflight")
        click.secho("--> Skipping migration checks", bold=True, fg="yellow")

    print_event("Running bolt compile")
    subprocess.check_call(["bolt", "compile"])

    if find_spec("bolt.pytest"):
        print_event("Running tests")
        subprocess.check_call(["bolt", "test"])


def bolt_db_connected():
    result = subprocess.run(
        [
            "bolt",
            "legacy",
            "showmigrations",
            "--skip-checks",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def print_event(msg, newline=True):
    arrow = click.style("-->", fg=214, bold=True)
    message = str(msg)
    if not newline:
        message += " "
    click.secho(f"{arrow} {message}", nl=newline)


def check_short(message, *args):
    print_event(message, newline=False)
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        click.secho("✘", fg="red")
        click.secho(result.stdout.decode("utf-8"))
        sys.exit(1)
    else:
        click.secho("✔", fg="green")
