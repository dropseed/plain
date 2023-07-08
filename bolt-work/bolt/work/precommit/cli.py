import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import click

from ..utils import boltpackage_installed, get_repo_root
from .install import install_git_hook


@click.command()
@click.option("--install", is_flag=True)
def cli(install):
    """Git pre-commit checks"""
    repo_root = get_repo_root()

    if install:
        install_git_hook(repo_root)
        return

    if repo_root and has_pyproject_toml(repo_root):
        with open(Path(repo_root, "pyproject.toml"), "rb") as f:
            pyproject = tomllib.load(f)
        for cmd in (
            pyproject.get("tool", {})
            .get("bolt", {})
            .get("pre-commit", {})
            .get("run", [])
        ):
            print_event("Running custom pre-commit check")
            print(cmd)
            result = subprocess.run(cmd, shell=True)
            if result.returncode != 0:
                sys.exit(result.returncode)

    if repo_root and is_using_poetry(repo_root):
        check_short("Checking poetry.lock", "poetry", "lock", "--check")

    if boltpackage_installed("format"):
        check_short("Checking code formatting", "bolt", "format", "--check")

    if django_db_connected():
        check_short(
            "Running Django system checks",
            "bolt",
            "django",
            "check",
            "--database",
            "default",
        )
        check_short(
            "Checking Django migrations", "bolt", "django", "migrate", "--check"
        )
        check_short(
            "Checking for Django models missing migrations",
            "bolt",
            "django",
            "makemigrations",
            "--dry-run",
            "--check",
        )
    else:
        check_short(
            "Running Django checks (without database)", "bolt", "django", "check"
        )
        click.secho("--> Skipping migration checks", bold=True, fg="yellow")

    if boltpackage_installed("test"):
        print_event("Running tests")
        subprocess.check_call(["bolt", "test"])


def django_db_connected():
    result = subprocess.run(
        [
            "bolt",
            "django",
            "showmigrations",
            "--skip-checks",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def is_using_poetry(target_path):
    return (Path(target_path) / "poetry.lock").exists()


def has_pyproject_toml(target_path):
    return (Path(target_path) / "pyproject.toml").exists()


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
