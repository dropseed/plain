import subprocess
import sys
import tomllib
from pathlib import Path

import click

from .runtime import without_runtime_setup

LOCK_FILE = Path("uv.lock")


@without_runtime_setup
@click.command()
@click.argument("packages", nargs=-1)
def upgrade(packages: tuple[str, ...]) -> None:
    """Upgrade Plain packages"""
    if not packages:
        click.secho("Getting installed packages...", bold=True)
        packages = tuple(sorted(get_installed_plain_packages()))
        for pkg in packages:
            click.secho(f"- {click.style(pkg, fg='yellow')}")
        click.echo()

    if not packages:
        raise click.UsageError("No plain packages found or specified.")

    before_after = upgrade_packages(packages)

    # Show what was upgraded
    upgraded = {
        pkg: versions
        for pkg, versions in before_after.items()
        if versions[0] != versions[1]
    }

    if not upgraded:
        click.secho("All packages already at latest version.", fg="green")
        return

    click.secho("Upgraded packages:", bold=True)
    for pkg, (before, after) in upgraded.items():
        click.echo(f"  {pkg}: {before} -> {after}")


def get_installed_plain_packages() -> list[str]:
    lock_text = LOCK_FILE.read_text()
    data = tomllib.loads(lock_text)
    names: list[str] = []
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        if name.startswith("plain") and name != "plain-upgrade":
            names.append(name)
    return names


def parse_lock_versions(lock_text: str, packages: set[str]) -> dict[str, str]:
    data = tomllib.loads(lock_text)
    versions: dict[str, str] = {}
    for pkg in data.get("package", []):
        name = pkg.get("name")
        if name in packages:
            versions[name] = pkg.get("version")
    return versions


def upgrade_packages(
    packages: tuple[str, ...],
) -> dict[str, tuple[str | None, str | None]]:
    before = parse_lock_versions(LOCK_FILE.read_text(), set(packages))

    upgrade_args = ["uv", "sync"]
    for pkg in packages:
        upgrade_args.extend(["--upgrade-package", pkg])

    click.secho("Upgrading with uv sync...", bold=True)
    subprocess.run(upgrade_args, check=True, stdout=sys.stderr)
    click.echo()

    after = parse_lock_versions(LOCK_FILE.read_text(), set(packages))
    return {pkg: (before.get(pkg), after.get(pkg)) for pkg in packages}
