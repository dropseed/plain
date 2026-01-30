from __future__ import annotations

import importlib.util
import json
import pkgutil
import shutil
from pathlib import Path

import click


def _get_agent_dirs() -> list[Path]:
    """Get list of agents/.claude/ directories from installed plain.* packages."""
    agent_dirs: list[Path] = []

    try:
        import plain

        # Check core plain package (namespace package)
        plain_spec = importlib.util.find_spec("plain")
        if plain_spec and plain_spec.submodule_search_locations:
            for location in plain_spec.submodule_search_locations:
                agent_dir = Path(location) / "agents" / ".claude"
                if agent_dir.exists() and agent_dir.is_dir():
                    agent_dirs.append(agent_dir)
                    break

        # Check other plain.* subpackages
        if hasattr(plain, "__path__"):
            for importer, modname, ispkg in pkgutil.iter_modules(
                plain.__path__, "plain."
            ):
                if ispkg:
                    try:
                        spec = importlib.util.find_spec(modname)
                        if spec and spec.origin:
                            agent_dir = Path(spec.origin).parent / "agents" / ".claude"
                            if agent_dir.exists() and agent_dir.is_dir():
                                agent_dirs.append(agent_dir)
                    except Exception:
                        continue
    except Exception:
        pass

    return agent_dirs


def _install_agent_dir(source_dir: Path, dest_dir: Path) -> tuple[int, int]:
    """Copy contents of a source agents/.claude/ dir to the project's .claude/ dir.

    Handles skills/ subdirectories and rules/ files.
    Returns (installed_count, removed_count) for reporting.
    """
    installed_count = 0

    # Copy skills (directories containing SKILL.md)
    source_skills = source_dir / "skills"
    if source_skills.exists():
        dest_skills = dest_dir / "skills"
        dest_skills.mkdir(parents=True, exist_ok=True)
        for skill_dir in source_skills.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                dest_skill = dest_skills / skill_dir.name
                # Check mtime to skip unchanged
                if dest_skill.exists():
                    source_mtime = (skill_dir / "SKILL.md").stat().st_mtime
                    dest_mtime = (
                        (dest_skill / "SKILL.md").stat().st_mtime
                        if (dest_skill / "SKILL.md").exists()
                        else 0
                    )
                    if source_mtime <= dest_mtime:
                        continue
                    shutil.rmtree(dest_skill)
                shutil.copytree(skill_dir, dest_skill)
                installed_count += 1

    # Copy rules (individual .md files)
    source_rules = source_dir / "rules"
    if source_rules.exists():
        dest_rules = dest_dir / "rules"
        dest_rules.mkdir(parents=True, exist_ok=True)
        for rule_file in source_rules.iterdir():
            if rule_file.is_file() and rule_file.suffix == ".md":
                dest_rule = dest_rules / rule_file.name
                # Check mtime to skip unchanged
                if dest_rule.exists():
                    if rule_file.stat().st_mtime <= dest_rule.stat().st_mtime:
                        continue
                shutil.copy2(rule_file, dest_rule)
                installed_count += 1

    return installed_count, 0


def _cleanup_orphans(dest_dir: Path, agent_dirs: list[Path]) -> int:
    """Remove plain* items from .claude/ that no longer exist in any source package."""
    removed_count = 0

    # Collect all source skill and rule names
    source_skills: set[str] = set()
    source_rules: set[str] = set()
    for agent_dir in agent_dirs:
        skills_dir = agent_dir / "skills"
        if skills_dir.exists():
            for d in skills_dir.iterdir():
                if d.is_dir() and (d / "SKILL.md").exists():
                    source_skills.add(d.name)
        rules_dir = agent_dir / "rules"
        if rules_dir.exists():
            for f in rules_dir.iterdir():
                if f.is_file() and f.suffix == ".md":
                    source_rules.add(f.name)

    # Remove orphaned skills
    dest_skills = dest_dir / "skills"
    if dest_skills.exists():
        for dest in dest_skills.iterdir():
            if (
                dest.is_dir()
                and dest.name.startswith("plain")
                and dest.name not in source_skills
            ):
                shutil.rmtree(dest)
                removed_count += 1

    # Remove orphaned rules
    dest_rules = dest_dir / "rules"
    if dest_rules.exists():
        for dest in dest_rules.iterdir():
            if (
                dest.is_file()
                and dest.name.startswith("plain")
                and dest.suffix == ".md"
                and dest.name not in source_rules
            ):
                dest.unlink()
                removed_count += 1

    return removed_count


def _cleanup_session_hook(dest_dir: Path) -> None:
    """Remove the old plain agent context SessionStart hook from settings.json."""
    settings_file = dest_dir / "settings.json"

    if not settings_file.exists():
        return

    settings = json.loads(settings_file.read_text())

    hooks = settings.get("hooks", {})
    session_hooks = hooks.get("SessionStart", [])

    # Remove any plain agent or plain-context.md hooks
    session_hooks = [h for h in session_hooks if "plain agent" not in str(h)]
    session_hooks = [h for h in session_hooks if "plain-context.md" not in str(h)]

    if session_hooks:
        hooks["SessionStart"] = session_hooks
    else:
        hooks.pop("SessionStart", None)

    if hooks:
        settings["hooks"] = hooks
    else:
        settings.pop("hooks", None)

    if settings:
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    else:
        settings_file.unlink()


@click.group()
def agent() -> None:
    """AI agent integration for Plain projects"""
    pass


@agent.command()
def install() -> None:
    """Install skills and rules to agent directories"""
    cwd = Path.cwd()
    claude_dir = cwd / ".claude"

    if not claude_dir.exists():
        click.secho("No .claude/ directory found.", fg="yellow")
        return

    agent_dirs = _get_agent_dirs()

    # Clean up orphaned plain-* items
    removed_count = _cleanup_orphans(claude_dir, agent_dirs)

    # Install from each package
    total_installed = 0
    for source_dir in agent_dirs:
        installed, _ = _install_agent_dir(source_dir, claude_dir)
        total_installed += installed

    # Clean up old session hook
    _cleanup_session_hook(claude_dir)

    parts = []
    if total_installed > 0:
        parts.append(f"installed {total_installed}")
    if removed_count > 0:
        parts.append(f"removed {removed_count}")
    click.echo(f"Agent: {', '.join(parts)} in .claude/") if parts else click.echo(
        "Agent: up to date"
    )


@agent.command()
def skills() -> None:
    """List available skills from installed packages"""
    agent_dirs = _get_agent_dirs()

    skill_names = []
    for agent_dir in agent_dirs:
        skills_dir = agent_dir / "skills"
        if skills_dir.exists():
            for d in skills_dir.iterdir():
                if d.is_dir() and (d / "SKILL.md").exists():
                    skill_names.append(d.name)

    if not skill_names:
        click.echo("No skills found in installed packages.")
        return

    click.echo("Available skills:")
    for name in sorted(skill_names):
        click.echo(f"  - {name}")
