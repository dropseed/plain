import subprocess
import sys
from pathlib import Path

import click


@click.command("contribute")
@click.option("--repo", default="../plain", help="Path to the plain repo")
@click.argument("packages", nargs=-1)
def cli(packages, repo):
    """Contribute to plain by linking packages locally."""

    if "reset" in packages:
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

    plain_packages = []
    plainx_packages = []

    for package in packages:
        package = package.replace(".", "-")
        click.secho(f"Linking {package} to {repo}", bold=True)
        if package == "plain" or package.startswith("plain-"):
            plain_packages.append(str(repo / package))
        elif package.startswith("plainx-"):
            plainx_packages.append(str(repo))
        else:
            click.secho(f"Unknown package {package}", fg="red")
            sys.exit(2)

    if plain_packages:
        result = subprocess.run(["uv", "add", "--editable", "--dev"] + plain_packages)
        if result.returncode:
            click.secho("Failed to link plain packages", fg="red")
            sys.exit(result.returncode)

    if plainx_packages:
        result = subprocess.run(["uv", "add", "--editable", "--dev"] + plainx_packages)
        if result.returncode:
            click.secho("Failed to link plainx packages", fg="red")
            sys.exit(result.returncode)
