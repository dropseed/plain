import importlib.util
import pkgutil
from pathlib import Path

import click

from .llmdocs import LLMDocs
from .output import iterate_markdown


@click.command()
@click.option("--open", is_flag=True, help="Open the README in your default editor")
@click.option("--source", is_flag=True, help="Include symbolicated source code")
@click.option("--list", "show_list", is_flag=True, help="List available packages")
@click.argument("module", default="")
def docs(module: str, open: bool, source: bool, show_list: bool) -> None:
    """Show documentation for a package"""
    if show_list:
        # List available packages
        available_packages = []
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
        return

    if not module:
        raise click.UsageError(
            "You must specify a module. Use --list to see available packages."
        )

    # Convert hyphens to dots (e.g., plain-models -> plain.models)
    module = module.replace("-", ".")

    # Automatically prefix if we need to
    if not module.startswith("plain"):
        module = f"plain.{module}"

    # Get the module path
    spec = importlib.util.find_spec(module)
    if not spec or not spec.origin:
        raise click.UsageError(f"Module {module} not found")

    module_path = Path(spec.origin).parent

    if source:
        # Output with symbolicated source
        source_docs = LLMDocs([module_path])
        source_docs.load()
        source_docs.print(relative_to=module_path.parent)
    else:
        # Human-readable README output
        readme_path = module_path / "README.md"
        if not readme_path.exists():
            raise click.UsageError(f"README.md not found for {module}")

        if open:
            click.launch(str(readme_path))
        else:
            click.echo_via_pager(iterate_markdown(readme_path.read_text()))
