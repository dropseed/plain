from __future__ import annotations

import importlib.util
import pkgutil
import shutil
from pathlib import Path

import click


def _get_packages_with_skills() -> dict[str, list[Path]]:
    """Get dict mapping package names to lists of skill directory paths.

    Each skill is a directory containing a SKILL.md file.
    """
    skills_dirs: dict[str, list[Path]] = {}

    # Check for plain.* subpackages (including core plain)
    try:
        import plain

        # Check core plain package (namespace package)
        plain_spec = importlib.util.find_spec("plain")
        if plain_spec and plain_spec.submodule_search_locations:
            # For namespace packages, check all search locations
            for location in plain_spec.submodule_search_locations:
                plain_path = Path(location)
                skills_dir = plain_path / "skills"
                if skills_dir.exists() and skills_dir.is_dir():
                    # Find subdirectories that contain SKILL.md
                    skill_dirs = [
                        d
                        for d in skills_dir.iterdir()
                        if d.is_dir() and (d / "SKILL.md").exists()
                    ]
                    if skill_dirs:
                        skills_dirs["plain"] = skill_dirs
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
                            # Look for skills/ directory at package root
                            skills_dir = package_path / "skills"
                            if skills_dir.exists() and skills_dir.is_dir():
                                # Find subdirectories that contain SKILL.md
                                skill_dirs = [
                                    d
                                    for d in skills_dir.iterdir()
                                    if d.is_dir() and (d / "SKILL.md").exists()
                                ]
                                if skill_dirs:
                                    skills_dirs[modname] = skill_dirs
                    except Exception:
                        continue
    except Exception:
        pass

    return skills_dirs


def _get_skill_destinations() -> list[Path]:
    """Get list of skill directories to install to based on what's present."""
    cwd = Path.cwd()
    destinations = []

    # Check for Claude (.claude/ directory)
    if (cwd / ".claude").exists():
        destinations.append(cwd / ".claude" / "skills")

    # Check for Codex (.codex/ directory)
    if (cwd / ".codex").exists():
        destinations.append(cwd / ".codex" / "skills")

    return destinations


def _install_skills_to(
    dest_skills_dir: Path, skills_by_package: dict[str, list[Path]]
) -> int:
    """Install skills to a destination directory. Returns count of installed skills."""
    dest_skills_dir.mkdir(parents=True, exist_ok=True)

    installed_count = 0

    for pkg_name in sorted(skills_by_package.keys()):
        for skill_dir in skills_by_package[pkg_name]:
            dest_dir = dest_skills_dir / skill_dir.name
            source_skill_file = skill_dir / "SKILL.md"

            # Check if we need to copy (mtime checking)
            if dest_dir.exists():
                dest_skill_file = dest_dir / "SKILL.md"
                if dest_skill_file.exists():
                    source_mtime = source_skill_file.stat().st_mtime
                    dest_mtime = dest_skill_file.stat().st_mtime
                    if source_mtime <= dest_mtime:
                        continue

            # Copy the entire skill directory
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(skill_dir, dest_dir)
            installed_count += 1

    return installed_count


@click.command()
@click.option(
    "--install/--no-install",
    is_flag=True,
    help="Install skills to agent directories",
)
def skills(install: bool) -> None:
    """Install skills from Plain packages"""

    skills_by_package = _get_packages_with_skills()

    if not skills_by_package:
        click.echo("No skills found in installed packages.")
        return

    if not install:
        # Just list available skills
        click.echo("Available skills:")
        for pkg_name in sorted(skills_by_package.keys()):
            for skill_dir in skills_by_package[pkg_name]:
                click.echo(f"  - {skill_dir.name} (from {pkg_name})")
        return

    # Find destinations based on what agent directories exist
    destinations = _get_skill_destinations()

    if not destinations:
        click.secho(
            "No agent directories found (.claude/ or .codex/)",
            fg="yellow",
        )
        return

    # Install to each destination
    for dest in destinations:
        installed_count = _install_skills_to(dest, skills_by_package)
        if installed_count > 0:
            click.echo(f"Installed {installed_count} skill(s) to {dest}/")
