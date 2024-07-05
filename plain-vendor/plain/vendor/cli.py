from pathlib import Path

import click

from plain.assets.finders import APP_ASSETS_DIR

from .deps import Dependency, get_deps
from .exceptions import DependencyError

VENDOR_DIR = APP_ASSETS_DIR / "vendor"


@click.group()
def cli():
    pass


@cli.command()
@click.option("--clear", is_flag=True, help="Clear all existing vendored dependencies")
def install(clear):
    if clear:
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
def update():
    deps = get_deps()
    if not deps:
        click.echo(
            "No vendored dependencies found in pyproject.toml. Use [tool.plain.vendor.dependencies]"
        )
        return

    errors = []

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
def add(url, name):
    if not name:
        name = url.split("/")[-1]

    dep = Dependency(name, url=url)

    click.secho(f"Installing {dep.name}...", bold=True, nl=False)

    try:
        vendored_path = dep.update()
    except DependencyError as e:
        click.secho(f"  {e}", fg="red")
        exit(1)

    vendored_path = vendored_path.relative_to(Path.cwd())

    click.secho(f" {dep.installed}", fg="green", nl=False)
    click.secho(f" -> {vendored_path}")
