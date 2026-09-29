import importlib.util
import json
import pkgutil
import shutil
from pathlib import Path

import click

from .runtime import without_runtime_setup


def _get_agent_dirs() -> list[Path]:
    """Get list of agents/.claude/ directories from installed plain.* and plainx.* packages."""
    agent_dirs: list[Path] = []

    # Search plain.* packages
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
                        # Best-effort plugin discovery; a broken package is skipped.
                        continue
    except Exception:
        pass

    # Search plainx.* packages
    try:
        import plainx

        # Check plainx.* subpackages
        if hasattr(plainx, "__path__"):
            for importer, modname, ispkg in pkgutil.iter_modules(
                plainx.__path__, "plainx."
            ):
                if ispkg:
                    try:
                        spec = importlib.util.find_spec(modname)
                        if spec and spec.origin:
                            agent_dir = Path(spec.origin).parent / "agents" / ".claude"
                            if agent_dir.exists() and agent_dir.is_dir():
                                agent_dirs.append(agent_dir)
                    except Exception:
                        # Best-effort plugin discovery; a broken package is skipped.
                        continue
    except Exception:
        pass

    return agent_dirs


def _files_in(directory: Path) -> dict[str, bytes]:
    """Every file under `directory`, by its path from it, with what it holds."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _install_agent_dir(source_dir: Path, dest_dir: Path) -> list[str]:
    """Copy what a package ships in its agents/.claude/ dir into the project's
    .claude/ dir.

    A rule or skill is written when the project doesn't have it, or has one
    that differs from what the package ships. That goes by what the files
    hold. It can't go by when they were written: a project's copy that git
    checked out an hour ago is newer than the package's and still the old
    text.

    Returns what was written, as paths from the .claude/ dir.
    """
    written: list[str] = []

    # Skills are directories holding a SKILL.md
    source_skills = source_dir / "skills"
    if source_skills.exists():
        dest_skills = dest_dir / "skills"
        dest_skills.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(source_skills.iterdir()):
            if not (skill_dir.is_dir() and (skill_dir / "SKILL.md").exists()):
                continue
            dest_skill = dest_skills / skill_dir.name
            if dest_skill.is_dir() and _files_in(dest_skill) == _files_in(skill_dir):
                continue
            if dest_skill.is_dir():
                shutil.rmtree(dest_skill)
            elif dest_skill.exists():
                dest_skill.unlink()
            shutil.copytree(skill_dir, dest_skill)
            written.append(f"skills/{skill_dir.name}")

    # Rules are single .md files
    source_rules = source_dir / "rules"
    if source_rules.exists():
        dest_rules = dest_dir / "rules"
        dest_rules.mkdir(parents=True, exist_ok=True)
        for rule_file in sorted(source_rules.iterdir()):
            if not (rule_file.is_file() and rule_file.suffix == ".md"):
                continue
            dest_rule = dest_rules / rule_file.name
            if dest_rule.is_file() and dest_rule.read_bytes() == rule_file.read_bytes():
                continue
            shutil.copy2(rule_file, dest_rule)
            written.append(f"rules/{rule_file.name}")

    return written


def _is_plain_item(name: str) -> bool:
    """Check if a name is from plain or plainx namespace."""
    return name.startswith("plain")  # Matches both 'plain' and 'plainx'


def _cleanup_orphans(dest_dir: Path, agent_dirs: list[Path]) -> list[str]:
    """Remove plain* and plainx* items from .claude/ that no longer exist in any source package.

    Returns what was removed, as paths from the .claude/ dir.
    """
    removed: list[str] = []

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
        for dest in sorted(dest_skills.iterdir()):
            if (
                dest.is_dir()
                and _is_plain_item(dest.name)
                and dest.name not in source_skills
            ):
                shutil.rmtree(dest)
                removed.append(f"skills/{dest.name}")

    # Remove orphaned rules
    dest_rules = dest_dir / "rules"
    if dest_rules.exists():
        for dest in sorted(dest_rules.iterdir()):
            if (
                dest.is_file()
                and _is_plain_item(dest.name)
                and dest.suffix == ".md"
                and dest.name not in source_rules
            ):
                dest.unlink()
                removed.append(f"rules/{dest.name}")

    return removed


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


@without_runtime_setup
@click.group()
def agent() -> None:
    """AI agent integration for Plain projects"""


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
    removed = _cleanup_orphans(claude_dir, agent_dirs)

    # Install from each package
    written: list[str] = []
    for source_dir in agent_dirs:
        written.extend(_install_agent_dir(source_dir, claude_dir))

    # Clean up old session hook
    _cleanup_session_hook(claude_dir)

    if not written and not removed:
        click.echo("Agent: up to date")
        return

    parts = []
    if written:
        parts.append(f"wrote {len(written)}")
    if removed:
        parts.append(f"removed {len(removed)}")
    click.echo(f"Agent: {', '.join(parts)} in .claude/")
    for path in written:
        click.echo(f"  wrote {path}")
    for path in removed:
        click.echo(f"  removed {path}")


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
