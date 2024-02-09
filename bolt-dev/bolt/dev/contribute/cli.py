import subprocess
import sys
from pathlib import Path

import click
import tomllib

from bolt.runtime import settings

REPO_URL = "https://github.com/dropseed/bolt"
REPO_DIR_NAME = "repo"


@click.group("contribute")
def cli():
    """Contribute to Bolt itself"""
    pass


@cli.command()
@click.option("--clone-depth", default=1, help="Depth to clone the repository")
def clone(clone_depth):
    """Clone the Bolt repository"""
    clone_target = settings.BOLT_TEMP_PATH / REPO_DIR_NAME
    click.secho(
        f"Cloning {REPO_URL} to {clone_target.relative_to(Path.cwd())}", bold=True
    )
    result = subprocess.run(
        ["git", "clone", REPO_URL, "--depth", str(clone_depth), str(clone_target)]
    )
    if result.returncode:
        click.secho("Failed to clone the repository", fg="red")
        sys.exit(result.returncode)


@cli.command()
@click.argument("package")
def link(package):
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        click.secho("pyproject.toml not found", fg="red")
        return

    poetry_group = "main"

    with pyproject.open("rb") as f:
        pyproject_data = tomllib.load(f)
        poetry_dependencies = (
            pyproject_data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        )

        for group_name, group_data in (
            pyproject_data.get("tool", {}).get("poetry", {}).get("group", {}).items()
        ):
            if package in group_data.get("dependencies", {}).keys():
                poetry_group = group_name
                break

        if not poetry_group and package not in poetry_dependencies.keys():
            click.secho(
                f"{package} not found in pyproject.toml (only poetry is supported)",
                fg="red",
            )
            return

    clone_target = settings.BOLT_TEMP_PATH / REPO_DIR_NAME

    click.secho(f"Linking {package} to {clone_target}", bold=True)
    if package == "bolt":
        result = subprocess.run(
            [
                "poetry",
                "add",
                "--editable",
                "--group",
                poetry_group,
                str(clone_target.relative_to(Path.cwd())),
            ]
        )
        if result.returncode:
            click.secho("Failed to link the package", fg="red")
            sys.exit(result.returncode)
    else:
        result = subprocess.run(
            [
                "poetry",
                "add",
                "--editable",
                "--group",
                poetry_group,
                str((clone_target / package).relative_to(Path.cwd())),
            ]
        )
        if result.returncode:
            click.secho("Failed to link the package", fg="red")
            sys.exit(result.returncode)
