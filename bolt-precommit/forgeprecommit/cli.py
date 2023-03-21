import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import click
from forgecore import Forge
from forgecore.packages import forgepackage_installed

from .install import install_git_hook


@click.command()
@click.option("--install", is_flag=True)
@click.pass_context
def cli(ctx, install):
    """Git pre-commit checks"""
    forge = Forge()

    if install:
        install_git_hook()
        return

    if forge.repo_root and has_pyproject_toml(forge.repo_root):
        with open(Path(forge.repo_root, "pyproject.toml"), "rb") as f:
            pyproject = tomllib.load(f)
        for cmd in pyproject.get("tool", {}).get("forge-precommit", {}).get("run", []):
            print_event("Running custom pre-commit check")
            print(cmd)
            result = subprocess.run(cmd, shell=True)
            if result.returncode != 0:
                sys.exit(result.returncode)

    if forge.repo_root and is_using_poetry(forge.repo_root):
        check_short("Checking poetry.lock", forge.venv_cmd, "poetry", "lock", "--check")

    if forgepackage_installed("format"):
        check_short(
            "Checking code formatting", forge.venv_cmd, "forge", "format", "--check"
        )

    if django_db_connected():
        check_short(
            "Running Django system checks",
            forge.manage_cmd,
            "check",
            "--database",
            "default",
        )
        check_short(
            "Checking Django migrations", forge.manage_cmd, "migrate", "--check"
        )
        check_short(
            "Checking for Django models missing migrations",
            forge.manage_cmd,
            "makemigrations",
            "--dry-run",
            "--check",
        )
    else:
        check_short(
            "Running Django checks (without database)", forge.manage_cmd, "check"
        )
        click.secho("--> Skipping migration checks", bold=True, fg="yellow")

    if forgepackage_installed("test"):
        print_event("Running tests")
        forge.venv_cmd("forge", "test", check=True)


def django_db_connected():
    result = Forge().manage_cmd(
        "showmigrations",
        "--skip-checks",
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


def check_short(message, func, *args):
    print_event(message, newline=False)
    result = func(*args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        click.secho("✘", fg="red")
        click.secho(result.stdout.decode("utf-8"))
        sys.exit(1)
    else:
        click.secho("✔", fg="green")
