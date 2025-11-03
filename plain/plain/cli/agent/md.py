from __future__ import annotations

import importlib.util
import pkgutil
from pathlib import Path

import click

from plain.runtime import PLAIN_TEMP_PATH

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
            # For namespace packages, check all search locations
            for location in plain_spec.submodule_search_locations:
                plain_path = Path(location)
                agents_path = plain_path / "AGENTS.md"
                if agents_path.exists():
                    agents_files["plain"] = agents_path
                    break  # Use the first one found

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
@click.option(
    "--save",
    default=None,
    is_flag=False,
    flag_value="PLAIN_TEMP_PATH",
    help="Save combined AGENTS.md from all packages to file (default: .plain/AGENTS.md)",
)
def md(save: str | None) -> None:
    """AGENTS.md from installed Plain packages"""

    agents_files = _get_packages_with_agents()

    if not agents_files:
        return

    # Handle --save flag
    if save:
        # Use PLAIN_TEMP_PATH if flag was used without value
        if save == "PLAIN_TEMP_PATH":
            save_path = PLAIN_TEMP_PATH / "AGENTS.md"
        else:
            save_path = Path(save)

        # Check if we need to regenerate
        if save_path.exists():
            output_mtime = save_path.stat().st_mtime
            # Check if any source file is newer
            needs_regen = any(
                path.stat().st_mtime > output_mtime for path in agents_files.values()
            )
            if not needs_regen:
                return

        # Ensure parent directory exists
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Generate combined file
        with save_path.open("w") as f:
            for pkg_name in sorted(agents_files.keys()):
                content = agents_files[pkg_name].read_text()
                f.write(content)
                if not content.endswith("\n"):
                    f.write("\n")
                f.write("\n")
    else:
        # Display to console
        for pkg in sorted(agents_files.keys()):
            agents_path = agents_files[pkg]
            for line in iterate_markdown(agents_path.read_text()):
                click.echo(line, nl=False)
            print()
