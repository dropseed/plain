"""Future channel CLI — opt projects into Plain's rolling unstable releases."""

from __future__ import annotations

import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import click
import tomlkit

from plain.cli import register_cli
from plain.cli.runtime import without_runtime_setup
from plain.cli.upgrade import get_installed_plain_packages

REPO_URL = "https://github.com/dropseed/plain"
RAW_URL_TEMPLATE = "https://raw.githubusercontent.com/dropseed/plain/{sha}/{path}"
PYPROJECT = Path("pyproject.toml")
LOCKFILE = Path("uv.lock")


def _normalize_git_url(url: str) -> str:
    return url.split("?", 1)[0].split("#", 1)[0]


def plain_package_sources(doc: tomlkit.TOMLDocument) -> dict[str, dict]:
    """tool.uv.sources entries that point at the dropseed/plain repo."""
    sources = doc.get("tool", {}).get("uv", {}).get("sources", {})
    return {
        name: entry
        for name, entry in sources.items()
        if isinstance(entry, dict)
        and _normalize_git_url(entry.get("git", "")) == REPO_URL
    }


def plain_package_shas() -> dict[str, str]:
    """{package: commit_sha} for packages tracked from the dropseed/plain repo."""
    data = tomllib.loads(LOCKFILE.read_text())
    shas: dict[str, str] = {}
    for pkg in data.get("package", []):
        source = pkg.get("source", {})
        if _normalize_git_url(source.get("git", "")) != REPO_URL:
            continue
        sha = source.get("rev") or source.get("requested-revision")
        if sha:
            shas[pkg.get("name", "")] = sha
    return shas


def fetch_future_md(package_name: str, sha: str) -> str | None:
    """Fetch <pkg>/plain/<sub>/FUTURE.md from github at the given commit. None if not present."""
    sub = package_name.removeprefix("plain-")
    path = f"{package_name}/plain/{sub}/FUTURE.md"
    url = RAW_URL_TEMPLATE.format(sha=sha, path=path)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


@without_runtime_setup
@register_cli("future")
@click.group(hidden=True)
def cli() -> None:
    """Track the Plain future channel (rolling unstable releases)"""


@cli.command()
@click.option(
    "--branch", default="future", help="Git branch on dropseed/plain to track"
)
def enable(branch: str) -> None:
    """Point installed plain packages at the future branch"""
    if not LOCKFILE.exists():
        raise click.ClickException("uv.lock not found — run from a uv project root")
    packages = sorted(get_installed_plain_packages())
    if not packages:
        raise click.UsageError("No plain packages found in uv.lock")

    doc = tomlkit.parse(PYPROJECT.read_text())
    tool = doc.setdefault("tool", tomlkit.table())
    uv = tool.setdefault("uv", tomlkit.table())
    sources = uv.setdefault("sources", tomlkit.table())

    click.secho(
        f"Tracking branch '{branch}' for {len(packages)} package(s):", bold=True
    )
    for pkg in packages:
        entry = tomlkit.inline_table()
        entry["git"] = REPO_URL
        entry["branch"] = branch
        entry["subdirectory"] = pkg
        sources[pkg] = entry
        click.echo(f"  - {pkg}")

    PYPROJECT.write_text(tomlkit.dumps(doc))

    click.secho("\nRunning uv sync...", bold=True)
    result = subprocess.run(["uv", "sync"])
    if result.returncode:
        click.secho(
            "uv sync failed — pyproject.toml was edited; revert with git if needed",
            fg="red",
        )
        sys.exit(result.returncode)

    click.secho(
        "\nDone. You're on the future channel — expect breaking changes between syncs.\n"
        "Run 'plain future upgrade' to advance and read upgrade notes.\n"
        "Run 'plain future disable' to revert to stable PyPI releases.",
        fg="green",
    )


@cli.command()
def disable() -> None:
    """Remove future-channel sources and revert to stable PyPI releases"""
    doc = tomlkit.parse(PYPROJECT.read_text())
    ours = plain_package_sources(doc)
    if not ours:
        click.secho("Future channel is not enabled", fg="yellow")
        return

    uv: Any = doc.get("tool", {}).get("uv", {})
    sources: Any = uv.get("sources", {})
    for name in ours:
        del sources[name]

    if not sources:
        del uv["sources"]

    PYPROJECT.write_text(tomlkit.dumps(doc))

    click.secho(f"Removed {len(ours)} future source(s)", bold=True)
    click.secho("Running uv sync...", bold=True)
    subprocess.run(["uv", "sync"], check=True)


@cli.command()
def upgrade() -> None:
    """Pull latest commits on the tracked branch and show FUTURE.md updates"""
    old_shas = plain_package_shas()
    if not old_shas:
        raise click.UsageError(
            "No plain packages are tracking the future channel. Run 'plain future enable' first."
        )

    cmd = ["uv", "sync"]
    for pkg in old_shas:
        cmd.extend(["--upgrade-package", pkg])

    click.secho("Pulling latest commits...", bold=True)
    result = subprocess.run(cmd)
    if result.returncode:
        sys.exit(result.returncode)

    new_shas = plain_package_shas()
    updated = [pkg for pkg in old_shas if old_shas.get(pkg) != new_shas.get(pkg)]

    if not updated:
        click.secho("\nAll packages already at latest commit.", fg="green")
        return

    click.secho(f"\nUpdated {len(updated)} package(s):", bold=True)
    for pkg in updated:
        click.echo(f"  {pkg}: {old_shas[pkg][:8]} -> {new_shas[pkg][:8]}")

    with ThreadPoolExecutor(max_workers=min(10, len(updated))) as executor:
        futures = {
            pkg: executor.submit(fetch_future_md, pkg, new_shas[pkg]) for pkg in updated
        }
        contents = {pkg: f.result() for pkg, f in futures.items()}

    click.echo()
    for pkg in updated:
        click.secho(f"=== {pkg} FUTURE.md ===", bold=True)
        content = contents[pkg]
        if content is None:
            click.secho(
                "  (No FUTURE.md at this commit — package may have graduated to stable. "
                "Check CHANGELOG.md.)",
                fg="yellow",
            )
        else:
            click.echo(content)
        click.echo()

    click.secho(
        "Review the upgrade instructions above and apply any required code changes.",
        fg="cyan",
    )
