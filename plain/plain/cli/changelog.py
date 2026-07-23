from __future__ import annotations

import re
from importlib.util import find_spec
from pathlib import Path

import click

from plain.utils.version import compare_versions, parse_version

from .output import style_markdown
from .runtime import without_runtime_setup

__all__ = ["compare_versions", "parse_version"]


@without_runtime_setup
@click.command("changelog")
@click.argument("package_label")
@click.option("--from", "from_version", help="Show entries from this version onwards")
@click.option("--to", "to_version", help="Show entries up to this version")
def changelog(
    package_label: str, from_version: str | None, to_version: str | None
) -> None:
    """Show changelog for a package"""
    module_name = package_label.replace("-", ".")
    spec = find_spec(module_name)
    if not spec:
        raise click.ClickException(f"Package {package_label} not found")

    if spec.origin:
        package_path = Path(spec.origin).resolve().parent
    elif spec.submodule_search_locations:
        package_path = Path(list(spec.submodule_search_locations)[0]).resolve()
    else:
        raise click.ClickException(f"Package {package_label} not found")

    changelog_path = package_path / "CHANGELOG.md"
    if not changelog_path.exists():
        raise click.ClickException(
            f"Changelog not found for {package_label} ({changelog_path})"
        )

    content = changelog_path.read_text()

    entries = []
    current_version = None
    current_lines = []
    version_re = re.compile(r"^## \[([^\]]+)\]")

    for line in content.splitlines(keepends=True):
        m = version_re.match(line)
        if m:
            if current_version is not None:
                entries.append((current_version, current_lines))
            current_version = m.group(1)
            current_lines = [line]
        else:
            if current_version is not None:
                current_lines.append(line)

    if current_version is not None:
        entries.append((current_version, current_lines))

    def version_found(version: str) -> bool:
        return any(compare_versions(v, version) == 0 for v, _ in entries)

    if from_version and not version_found(from_version):
        click.secho(
            f"Warning: version {from_version} not found in changelog",
            fg="yellow",
            err=True,
        )

    selected_lines = []
    for version, lines in entries:
        if from_version and compare_versions(version, from_version) <= 0:
            continue
        if to_version and compare_versions(version, to_version) > 0:
            continue
        selected_lines.extend(lines)

    if not selected_lines:
        return

    click.echo(style_markdown("".join(selected_lines)))
