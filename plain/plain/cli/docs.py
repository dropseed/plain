import importlib.util
from pathlib import Path

import click

from .output import iterate_markdown


@click.command()
@click.option("--open", is_flag=True, help="Open the README in your default editor")
@click.argument("module", default="")
def docs(module: str, open: bool) -> None:
    """Show documentation for a package"""
    if not module:
        raise click.UsageError(
            "You must specify a module. For LLM-friendly docs, use `plain agent docs`."
        )

    # Convert hyphens to dots (e.g., plain-models -> plain.models)
    module = module.replace("-", ".")

    # Automatically prefix if we need to
    if not module.startswith("plain"):
        module = f"plain.{module}"

    # Get the README.md file for the module
    spec = importlib.util.find_spec(module)
    if not spec:
        raise click.UsageError(f"Module {module} not found")

    module_path = Path(spec.origin).parent
    readme_path = module_path / "README.md"
    if not readme_path.exists():
        raise click.UsageError(f"README.md not found for {module}")

    if open:
        click.launch(str(readme_path))
    else:
        click.echo_via_pager(iterate_markdown(readme_path.read_text()))
