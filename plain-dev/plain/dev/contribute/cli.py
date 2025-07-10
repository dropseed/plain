import subprocess
import sys
from pathlib import Path

import click

from plain.cli import register_cli


@register_cli("contrib")
@click.command("contribute", hidden=True)
@click.option("--repo", default="../plain", help="Path to the plain repo")
@click.option(
    "--reset", is_flag=True, help="Undo any changes to pyproject.toml and uv.lock"
)
@click.option(
    "--all", "all_packages", is_flag=True, help="Link all installed plain packages"
)
@click.argument("packages", nargs=-1)
def cli(packages, repo, reset, all_packages):
    """Contribute to plain by linking packages locally."""

    if reset:
        click.secho("Undoing any changes to pyproject.toml and uv.lock", bold=True)
        result = subprocess.run(["git", "checkout", "pyproject.toml", "uv.lock"])
        if result.returncode:
            click.secho("Failed to checkout pyproject.toml and uv.lock", fg="red")
            sys.exit(result.returncode)

        click.secho("Running uv sync", bold=True)
        result = subprocess.run(["uv", "sync", "--reinstall"])
        if result.returncode:
            click.secho("Failed to sync", fg="red")
            sys.exit(result.returncode)

        return

    packages = list(packages)

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
    skipped_plainx_packages = []

    if all_packages:
        # get all installed plain packages
        output = subprocess.check_output(["uv", "pip", "freeze"])

        installed_packages = output.decode()
        if not installed_packages:
            click.secho("No installed packages found", fg="red")
            sys.exit(1)

        packages = []
        for line in installed_packages.splitlines():
            if not line.startswith("plain"):
                continue
            package = line.split("==")[0]
            if package.startswith("plainx-"):
                skipped_plainx_packages.append(package)
            else:
                packages.append(package)

        if skipped_plainx_packages:
            click.secho(
                "Skipping plainx packages: "
                + ", ".join(sorted(skipped_plainx_packages))
                + " (unknown repo)",
                fg="yellow",
            )

    for package in packages:
        package = package.replace(".", "-")
        click.secho(f"Linking {package} to {repo}", bold=True)
        if package == "plain" or package.startswith("plain-"):
            plain_packages.append(str(repo / package))
        elif package.startswith("plainx-"):
            plainx_packages.append(str(repo))
        else:
            raise click.UsageError(f"Unknown package {package}")

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
