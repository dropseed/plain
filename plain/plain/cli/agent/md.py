from __future__ import annotations

import importlib.util
import pkgutil
from pathlib import Path

import click

from ..output import iterate_markdown


def _get_packages_with_agents() -> dict[str, Path]:
    """Get dict mapping package names to AGENTS.md paths."""
    agents_files = {}

    # Check for plain.* subpackages (including core plain)
    try:
        import plain

        # Check core plain package (namespace package)
        plain_spec = importlib.util.find_spec("plain")
        if plain_spec and plain_spec.submodule_search_locations:
            # For namespace packages, use the first search location
            plain_path = Path(plain_spec.submodule_search_locations[0])
            agents_path = plain_path / "AGENTS.md"
            if agents_path.exists():
                agents_files["plain"] = agents_path

        # Check other plain.* subpackages
        if hasattr(plain, "__path__"):
            for importer, modname, ispkg in pkgutil.iter_modules(
                plain.__path__, "plain."
            ):
                if ispkg:
                    try:
                        spec = importlib.util.find_spec(modname)
                        if spec and spec.origin:
                            package_path = Path(spec.origin).parent
                            # Look for AGENTS.md at package root
                            agents_path = package_path / "AGENTS.md"
                            if agents_path.exists():
                                agents_files[modname] = agents_path
                    except Exception:
                        continue
    except Exception:
        pass

    return agents_files


@click.command("md")
@click.argument("package", default="", required=False)
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    help="Show AGENTS.md for all packages that have them",
)
@click.option(
    "--list",
    "show_list",
    is_flag=True,
    help="List packages with AGENTS.md files",
)
def md(package: str, show_all: bool, show_list: bool) -> None:
    """Show AGENTS.md for a package."""

    agents_files = _get_packages_with_agents()

    if show_list:
        for pkg in sorted(agents_files.keys()):
            click.echo(f"- {pkg}")

        return

    if show_all:
        for pkg in sorted(agents_files.keys()):
            agents_path = agents_files[pkg]
            for line in iterate_markdown(agents_path.read_text()):
                click.echo(line, nl=False)
            print()

        return

    if not package:
        raise click.UsageError(
            "Package name or --all required. Use --list to see available packages."
        )

    agents_path = agents_files[package]
    for line in iterate_markdown(agents_path.read_text()):
        click.echo(line, nl=False)
