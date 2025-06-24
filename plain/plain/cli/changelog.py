import re
from importlib.util import find_spec
from pathlib import Path

import click
from packaging.version import Version

from .output import style_markdown


@click.command("changelog")
@click.argument("package_label")
@click.option("--from", "from_version", help="Show entries from this version onwards")
@click.option("--to", "to_version", help="Show entries up to this version")
def changelog(package_label, from_version, to_version):
    """Show changelog entries for a package."""
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
        raise click.ClickException(f"Changelog not found for {package_label}")

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

    def version_found(version):
        return any(Version(v) == Version(version) for v, _ in entries)

    if from_version and not version_found(from_version):
        click.secho(
            f"Warning: version {from_version} not found in changelog",
            fg="yellow",
            err=True,
        )

    selected_lines = []
    for version, lines in entries:
        v = Version(version)
        if from_version and v <= Version(from_version):
            continue
        if to_version and v > Version(to_version):
            continue
        selected_lines.extend(lines)

    if not selected_lines:
        return

    click.echo(style_markdown("".join(selected_lines)))
