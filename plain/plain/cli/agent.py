from __future__ import annotations

import importlib.util
import json
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
) -> tuple[int, int]:
    """Install skills to a destination directory. Returns (installed_count, removed_count)."""
    dest_skills_dir.mkdir(parents=True, exist_ok=True)

    # Collect all source skill names
    source_skill_names: set[str] = set()
    for skill_dirs in skills_by_package.values():
        for skill_dir in skill_dirs:
            source_skill_names.add(skill_dir.name)

    installed_count = 0
    removed_count = 0

    # Remove orphaned plain-* skills (exist in dest but not in source)
    # Only remove skills with plain- prefix to preserve user-created skills
    if dest_skills_dir.exists():
        for dest_dir in dest_skills_dir.iterdir():
            if (
                dest_dir.is_dir()
                and dest_dir.name.startswith("plain-")
                and dest_dir.name not in source_skill_names
            ):
                shutil.rmtree(dest_dir)
                removed_count += 1

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

    return installed_count, removed_count


def _setup_session_hook(dest_dir: Path) -> None:
    """Create or update settings.json with SessionStart hook."""
    settings_file = dest_dir / "settings.json"

    # Load existing settings or start fresh
    if settings_file.exists():
        settings = json.loads(settings_file.read_text())
    else:
        settings = {}

    # Ensure hooks structure exists
    if "hooks" not in settings:
        settings["hooks"] = {}

    # Define the Plain hook - calls the agent context command directly
    plain_hook = {
        "matcher": "startup|resume",
        "hooks": [
            {
                "type": "command",
                "command": "uv run plain agent context 2>/dev/null || true",
            }
        ],
    }

    # Get existing SessionStart hooks, remove any existing plain hook
    session_hooks = settings["hooks"].get("SessionStart", [])
    session_hooks = [h for h in session_hooks if "plain agent" not in str(h)]
    # Also remove old plain-context.md hooks for migration
    session_hooks = [h for h in session_hooks if "plain-context.md" not in str(h)]
    session_hooks.append(plain_hook)
    settings["hooks"]["SessionStart"] = session_hooks

    settings_file.write_text(json.dumps(settings, indent=2) + "\n")


@click.group()
def agent() -> None:
    """AI agent integration for Plain projects"""
    pass


@agent.command()
def context() -> None:
    """Output Plain framework context for AI agents"""
    click.echo("This is a Plain project. Use the /plain-* skills for common tasks.")


@agent.command()
def install() -> None:
    """Install skills and hooks to agent directories"""
    skills_by_package = _get_packages_with_skills()

    if not skills_by_package:
        click.echo("No skills found in installed packages.")
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
        installed_count, removed_count = _install_skills_to(dest, skills_by_package)

        parent_dir = dest.parent  # .claude/ or .codex/

        # Setup hook only for Claude (Codex uses a different config format)
        if parent_dir.name == ".claude":
            _setup_session_hook(parent_dir)

        parts = []
        if installed_count > 0:
            parts.append(f"installed {installed_count} skills")
        if removed_count > 0:
            parts.append(f"removed {removed_count} skills")
        if parent_dir.name == ".claude":
            parts.append("updated hooks")
        if parts:
            click.echo(f"Agent: {', '.join(parts)} in {parent_dir}/")


@agent.command()
def skills() -> None:
    """List available skills from installed packages"""
    skills_by_package = _get_packages_with_skills()

    if not skills_by_package:
        click.echo("No skills found in installed packages.")
        return

    click.echo("Available skills:")
    for pkg_name in sorted(skills_by_package.keys()):
        for skill_dir in skills_by_package[pkg_name]:
            click.echo(f"  - {skill_dir.name} (from {pkg_name})")
