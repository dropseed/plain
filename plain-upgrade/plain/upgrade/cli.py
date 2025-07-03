import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import click

LOCK_FILE = Path("uv.lock")


@click.command()
@click.argument("packages", nargs=-1)
@click.option(
    "--diff", is_flag=True, help="Read versions from unstaged uv.lock changes"
)
@click.option(
    "--agent-command",
    envvar="PLAIN_UPGRADE_AGENT_COMMAND",
    help="Run command with generated prompt",
)
def cli(
    packages: tuple[str, ...], diff: bool, agent_command: str | None = None
) -> None:
    """Generate an upgrade prompt for plain packages."""
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

    if agent_command:
        cmd = shlex.split(agent_command)
        cmd.append(prompt)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            click.secho(
                f"Agent command failed with exit code {result.returncode}",
                fg="red",
                err=True,
            )
    else:
        click.secho(
            "\nCopy this prompt to a coding agent. To run an agent automatically, use --agent-command or set the PLAIN_UPGRADE_AGENT_COMMAND environment variable.\n",
            dim=True,
            italic=True,
            err=True,
        )
        click.echo(prompt)


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

    ast_grep_path = shutil.which("ast-grep")

    lines.extend(
        [
            "",
            'Work through each package in order. Use `uv run plain-changelog {package} --from {before} --to {after}` and read the "Upgrade instructions" to see if any changes need to be made. If it says "No changes required", then you don\'t need to do anything for that version.',
            "Do not test after each package -- wait until ALL packages are done before checking results with `uv run plain pre-commit`.",
            f"Do not commit any changes. You can also use the ast-grep CLI tool for code structural search and rewriting (located at {ast_grep_path}).",
        ]
    )
    return "\n".join(lines)
