import subprocess
import sys
from pathlib import Path

import click
import tomllib


@click.command("contribute")
@click.option("--repo", default="../plain", help="Path to the plain repo")
@click.argument("package")
def cli(package, repo):
    """Contribute to plain by linking a package locally."""

    if package == "reset":
        click.secho("Undoing any changes to pyproject.toml and poetry.lock", bold=True)
        result = subprocess.run(["git", "checkout", "pyproject.toml", "poetry.lock"])
        if result.returncode:
            click.secho("Failed to checkout pyproject.toml and poetry.lock", fg="red")
            sys.exit(result.returncode)

        click.secho("Removing current .venv", bold=True)
        result = subprocess.run(["rm", "-rf", ".venv"])
        if result.returncode:
            click.secho("Failed to remove .venv", fg="red")
            sys.exit(result.returncode)

        click.secho("Running poetry install", bold=True)
        result = subprocess.run(["poetry", "install"])
        if result.returncode:
            click.secho("Failed to install", fg="red")
            sys.exit(result.returncode)

        return

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
    if package == "plain" or package.startswith("plain-"):
        result = subprocess.run(
            [
                "poetry",
                "add",
                "--editable",
                "--group",
                poetry_group,
                str(repo / package),  # Link a subdirectory
            ]
        )
        if result.returncode:
            click.secho("Failed to link the package", fg="red")
            sys.exit(result.returncode)
    elif package.startswith("plainx-"):
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
        click.secho(f"Unknown package {package}", fg="red")
        sys.exit(2)
