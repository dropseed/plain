from pathlib import Path

import click

from plain.assets.finders import APP_ASSETS_DIR

from .deps import Dependency, get_deps
from .exceptions import DependencyError

VENDOR_DIR = APP_ASSETS_DIR / "vendor"


@click.group()
def cli():
    """Vendor CSS/JS from a CDN"""
    pass


@cli.command()
def sync():
    """Clear vendored assets and re-download"""
    click.secho("Clearing existing vendored dependencies...", bold=True)
    if VENDOR_DIR.exists():
        for path in VENDOR_DIR.iterdir():
            path.unlink()

    deps = get_deps()
    if not deps:
        click.echo(
            "No vendored dependencies found in pyproject.toml. Use [tool.plain.vendor.dependencies]"
        )
        return

    errors = []

    for dep in deps:
        click.secho(f"Installing {dep.name}...", bold=True, nl=False)
        try:
            vendored_path = dep.install()
        except DependencyError as e:
            click.secho(f"  {e}", fg="red")
            errors.append(e)

        vendored_path = vendored_path.relative_to(Path.cwd())

        click.secho(f" {dep.installed}", fg="green", nl=False)
        click.secho(f" -> {vendored_path}")

    if errors:
        click.secho("Failed to install some dependencies.", fg="red")
        exit(1)


@cli.command()
@click.argument("name", nargs=-1, default=None)
def update(name):
    """Update vendored dependencies in pyproject.toml"""
    deps = get_deps()
    if not deps:
        click.echo(
            "No vendored dependencies found in pyproject.toml. Use [tool.plain.vendor.dependencies]"
        )
        return

    errors = []

    if name:
        deps = [dep for dep in deps if dep.name in name]
        if len(deps) != len(name):
            not_found = set(name) - {dep.name for dep in deps}
            click.secho(
                f"Some dependencies not found: {', '.join(not_found)}", fg="red"
            )
            exit(1)

    for dep in deps:
        click.secho(f"Updating {dep.name} {dep.installed}...", bold=True, nl=False)
        try:
            vendored_path = dep.update()
            vendored_path = vendored_path.relative_to(Path.cwd())

            click.secho(f" {dep.installed}", fg="green", nl=False)
            click.secho(f" -> {vendored_path}")
        except DependencyError as e:
            click.secho(f"  {e}", fg="red")
            errors.append(e)

    if errors:
        click.secho("Failed to install some dependencies.", fg="red")
        exit(1)


@cli.command()
@click.argument("url")
@click.option("--name", help="Name of the dependency")
@click.option("--sourcemap/--no-sourcemap", default=True, help="Download sourcemap")
def add(url, name, sourcemap):
    """Add a new vendored dependency to pyproject.toml"""
    if not name:
        name = url.split("/")[-1]

    dep = Dependency(name, url=url, sourcemap=sourcemap)

    click.secho(f"Installing {dep.name}", bold=True, nl=False)

    try:
        vendored_path = dep.update()
    except DependencyError as e:
        click.secho(f"  {e}", fg="red")
        exit(1)

    vendored_path = vendored_path.relative_to(Path.cwd())

    click.secho(f" {dep.installed}", fg="green", nl=False)
    click.secho(f" -> {vendored_path}")

    if not dep.installed:
        click.secho(
            "No version was parsed from the url. You can configure it manually if you need to.",
            fg="yellow",
        )
