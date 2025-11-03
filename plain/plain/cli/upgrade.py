import subprocess
import sys
import tomllib
from pathlib import Path

import click

from .agent.prompt import prompt_agent
from .runtime import without_runtime_setup

LOCK_FILE = Path("uv.lock")


@without_runtime_setup
@click.command()
@click.argument("packages", nargs=-1)
@click.option(
    "--diff", is_flag=True, help="Read versions from unstaged uv.lock changes"
)
@click.option(
    "--agent-command",
    envvar="PLAIN_AGENT_COMMAND",
    help="Run command with generated prompt",
)
@click.option(
    "--print",
    "print_only",
    is_flag=True,
    help="Print the prompt without running the agent",
)
def upgrade(
    packages: tuple[str, ...],
    diff: bool,
    agent_command: str | None = None,
    print_only: bool = False,
) -> None:
    """Upgrade Plain packages with agent assistance"""
    if not packages:
        click.secho("Getting installed packages...", bold=True, err=True)
        packages = tuple(sorted(get_installed_plain_packages()))
        for pkg in packages:
            click.secho(f"- {click.style(pkg, fg='yellow')}", err=True)
        click.echo(err=True)

    if not packages:
        raise click.UsageError("No plain packages found or specified.")

    if diff:
        before_after = versions_from_diff(packages)
    else:
        before_after = upgrade_packages(packages)

    # Remove all packages that were not upgraded
    before_after = {
        pkg: versions
        for pkg, versions in before_after.items()
        if versions[0] != versions[1]
    }

    if not before_after:
        click.secho(
            "No packages were upgraded. If uv.lock has already been updated, use --diff instead.",
            fg="green",
            err=True,
        )
        return

    prompt = build_prompt(before_after)
    success = prompt_agent(prompt, agent_command, print_only)
    if not success:
        raise click.Abort()


def get_installed_plain_packages() -> list[str]:
    lock_text = LOCK_FILE.read_text()
    data = tomllib.loads(lock_text)
    names: list[str] = []
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        if name.startswith("plain") and name != "plain-upgrade":
            names.append(name)
    return names


def parse_lock_versions(lock_text: str, packages: set[str]) -> dict[str, str]:
    data = tomllib.loads(lock_text)
    versions: dict[str, str] = {}
    for pkg in data.get("package", []):
        name = pkg.get("name")
        if name in packages:
            versions[name] = pkg.get("version")
    return versions


def versions_from_diff(
    packages: tuple[str, ...],
) -> dict[str, tuple[str | None, str | None]]:
    result = subprocess.run(
        ["git", "status", "--porcelain", str(LOCK_FILE)], capture_output=True, text=True
    )
    if not result.stdout.strip():
        raise click.UsageError(
            "--diff specified but uv.lock has no uncommitted changes"
        )

    prev_text = subprocess.run(
        ["git", "show", f"HEAD:{LOCK_FILE}"], capture_output=True, text=True, check=True
    ).stdout
    current_text = LOCK_FILE.read_text()

    packages_set = set(packages)
    before = parse_lock_versions(prev_text, packages_set)
    after = parse_lock_versions(current_text, packages_set)

    return {pkg: (before.get(pkg), after.get(pkg)) for pkg in packages}


def upgrade_packages(
    packages: tuple[str, ...],
) -> dict[str, tuple[str | None, str | None]]:
    before = parse_lock_versions(LOCK_FILE.read_text(), set(packages))

    upgrade_args = ["uv", "sync"]
    for pkg in packages:
        upgrade_args.extend(["--upgrade-package", pkg])

    click.secho("Upgrading with uv sync...", bold=True, err=True)
    subprocess.run(upgrade_args, check=True, stdout=sys.stderr)
    click.echo(err=True)

    after = parse_lock_versions(LOCK_FILE.read_text(), set(packages))
    return {pkg: (before.get(pkg), after.get(pkg)) for pkg in packages}


def build_prompt(before_after: dict[str, tuple[str | None, str | None]]) -> str:
    lines = [
        "These packages have been updated and may require additional changes to the code:",
        "",
    ]
    for pkg, (before, after) in before_after.items():
        lines.append(f"- {pkg}: {before} -> {after}")

    lines.extend(
        [
            "",
            "## Instructions",
            "",
            "1. **Process each package systematically:**",
            "   - For each package, run: `uv run plain changelog {package} --from {before} --to {after}`",
            "   - Read the 'Upgrade instructions' section carefully",
            "   - If it says 'No changes required', skip to the next package",
            "   - Apply any required code changes as specified",
            "",
            "2. **Important guidelines:**",
            "   - Process ALL packages before testing or validation",
            "   - After all packages are updated, run `uv run plain fix --unsafe-fixes` and `uv run plain pre-commit` to check results",
            "   - DO NOT commit any changes",
            "   - Keep code changes minimal and focused - avoid unnecessary comments",
            "",
            "3. **Available tools:**",
            "   - Python shell: `uv run python`",
            "   - If you have a subagents feature and there are more than three packages here, use subagents",
            "",
            "4. **Workflow:**",
            "   - Review changelog for each package → Apply changes → Move to next package",
            "   - Only after all packages: run pre-commit checks",
            "   - Report any issues or conflicts encountered",
        ]
    )
    return "\n".join(lines)
