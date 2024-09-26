import subprocess
import sys
from pathlib import Path

import click


@click.command("contribute")
@click.option("--repo", default="../plain", help="Path to the plain repo")
@click.argument("package")
def cli(package, repo):
    """Contribute to plain by linking a package locally."""

    if package == "reset":
        click.secho("Undoing any changes to pyproject.toml and uv.lock", bold=True)
        result = subprocess.run(["git", "checkout", "pyproject.toml", "uv.lock"])
        if result.returncode:
            click.secho("Failed to checkout pyproject.toml and uv.lock", fg="red")
            sys.exit(result.returncode)

        click.secho("Running uv sync", bold=True)
        result = subprocess.run(["uv", "sync"])
        if result.returncode:
            click.secho("Failed to sync", fg="red")
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

    click.secho(f"Linking {package} to {repo}", bold=True)
    if package == "plain" or package.startswith("plain-"):
        result = subprocess.run(
            [
                "uv",
                "add",
                "--editable",
                "--dev",
                str(repo / package),  # Link a subdirectory
            ]
        )
        if result.returncode:
            click.secho("Failed to link the package", fg="red")
            sys.exit(result.returncode)
    elif package.startswith("plainx-"):
        result = subprocess.run(
            [
                "uv",
                "add",
                "--editable",
                "--dev",
                str(repo),
            ]
        )
        if result.returncode:
            click.secho("Failed to link the package", fg="red")
            sys.exit(result.returncode)
    else:
        click.secho(f"Unknown package {package}", fg="red")
        sys.exit(2)
