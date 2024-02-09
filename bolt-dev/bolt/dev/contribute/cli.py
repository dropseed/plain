import subprocess
import sys
from pathlib import Path

import click
import tomllib


@click.group("contribute")
def cli():
    """Contribute to Bolt itself"""
    pass


@cli.command()
@click.option("--repo", default="../bolt", help="Path to the bolt repo")
@click.argument("package")
def link(package, repo):
    repo = Path(repo)
    if not repo.exists():
        click.secho(f"Repo not found at {repo}", fg="red")
        return

    repo_branch = (
        subprocess.check_output(
            [
                "git",
                "rev-parse",
                "--abbrev-ref",
                "HEAD",
            ],
            cwd=repo,
        )
        .decode()
        .strip()
    )
    click.secho(f"Using repo at {repo} ({repo_branch} branch)", bold=True)

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

    click.secho(f"Linking {package} to {repo}", bold=True)
    if package == "bolt":
        result = subprocess.run(
            [
                "poetry",
                "add",
                "--editable",
                "--group",
                poetry_group,
                str(repo),
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
                str(repo / package),
            ]
        )
        if result.returncode:
            click.secho("Failed to link the package", fg="red")
            sys.exit(result.returncode)
