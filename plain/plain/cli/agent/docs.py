import importlib.util
import pkgutil
from pathlib import Path

import click

from .llmdocs import LLMDocs


@click.command()
@click.argument("package", default="", required=False)
@click.option(
    "--list",
    "show_list",
    is_flag=True,
    help="List available packages",
)
def docs(package: str, show_list: bool) -> None:
    """Show LLM-friendly documentation for a package"""

    if show_list:
        # List available packages using same discovery logic as md command
        try:
            available_packages = []

            # Check for plain.* subpackages (including core plain)
            try:
                import plain

                # Check core plain package (namespace package)
                plain_spec = importlib.util.find_spec("plain")
                if plain_spec and plain_spec.submodule_search_locations:
                    available_packages.append("plain")

                # Check other plain.* subpackages
                if hasattr(plain, "__path__"):
                    for importer, modname, ispkg in pkgutil.iter_modules(
                        plain.__path__, "plain."
                    ):
                        if ispkg:
                            available_packages.append(modname)
            except Exception:
                pass

            if available_packages:
                for pkg in sorted(available_packages):
                    click.echo(f"- {pkg}")
            else:
                click.echo("No packages found.")
        except Exception as e:
            click.echo(f"Error listing packages: {e}")
        return

    if not package:
        raise click.UsageError(
            "Package name required. Usage: plain agent docs [package-name]"
        )

    # Convert hyphens to dots (e.g., plain-models -> plain.models)
    package = package.replace("-", ".")

    # Automatically prefix if we need to
    if not package.startswith("plain"):
        package = f"plain.{package}"

    try:
        # Get the path for this specific package
        spec = importlib.util.find_spec(package)
        if not spec or not spec.origin:
            raise click.UsageError(f"Package {package} not found")

        package_path = Path(spec.origin).parent
        paths = [package_path]

        # Generate docs for this specific package
        source_docs = LLMDocs(paths)
        source_docs.load()
        source_docs.print(relative_to=package_path.parent)

    except Exception as e:
        raise click.UsageError(f"Error loading documentation for {package}: {e}")
