from __future__ import annotations

import json
import os
import subprocess
import tomllib
from importlib.util import find_spec
from pathlib import Path

import click

from plain.cli.print import print_event
from plain.cli.runtime import common_command


def plain_db_connected() -> bool:
    result = subprocess.run(
        ["plain", "migrations", "list"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def check_short(message: str, *args: str) -> None:
    print_event(message, newline=False)
    env = {**os.environ, "FORCE_COLOR": "1"}
    result = subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env
    )
    if result.returncode != 0:
        click.secho("✘", fg="red")
        click.secho(result.stdout.decode("utf-8"))
        raise SystemExit(1)
    else:
        click.secho("✔", fg="green")


def check_preflight() -> None:
    """Run preflight for `plain check`, surfacing warnings even on success.

    Preflight warnings (e.g. duplicate indexes) are advisory — they don't fail
    the run — but `check_short` swallows captured output on success, so a
    passing run with warnings hid them and they were easy to miss. Show a
    warning count on success; on failure, print preflight's full report.
    """
    print_event("plain preflight", newline=False)
    env = {**os.environ, "FORCE_COLOR": "1"}
    result = subprocess.run(
        ["plain", "preflight", "--format", "json"],
        capture_output=True,
        env=env,
    )

    if result.returncode != 0:
        # Errors fail the check. Re-run preflight so its full, human-readable
        # report streams out, rather than reconstructing a partial one here.
        click.secho("✘", fg="red")
        subprocess.run(["plain", "preflight"], env=env)
        raise SystemExit(1)

    # Success — count warnings from the JSON to surface them; any parse hiccup
    # just falls back to a bare check rather than failing the run.
    try:
        data = json.loads(result.stdout.decode("utf-8"))
        warning_count = sum(
            1
            for check in data["checks"]
            for issue in check["issues"]
            if issue["warning"]
        )
    except (json.JSONDecodeError, KeyError):
        warning_count = 0

    if warning_count:
        plural = "s" if warning_count != 1 else ""
        click.secho("✔", fg="green", nl=False)
        click.secho(
            f" ({warning_count} warning{plural} — run `plain preflight` to see them)",
            fg="yellow",
        )
    else:
        click.secho("✔", fg="green")


def run_custom_checks() -> None:
    """Run custom checks from [tool.plain.check.run] in pyproject.toml."""
    pyproject_path = Path("pyproject.toml")

    if not pyproject_path.exists():
        return

    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)

    for name, data in (
        pyproject.get("tool", {}).get("plain", {}).get("check", {}).get("run", {})
    ).items():
        cmd = data["cmd"]
        print_event(f"Custom: {cmd}")
        result = subprocess.run(cmd, shell=True)
        if result.returncode != 0:
            raise SystemExit(result.returncode)


def run_core_checks(*, skip_test: bool = False) -> None:
    """Run core validation checks: custom, code, preflight, migrations, tests."""

    run_custom_checks()

    if find_spec("plain.code"):
        check_short("plain code check", "plain", "code", "check")

    check_preflight()

    if plain_db_connected():
        check_short(
            "plain postgres sync --check", "plain", "postgres", "sync", "--check"
        )
    else:
        click.secho("--> Skipping sync check", bold=True, fg="yellow")

    if not skip_test and find_spec("plain.pytest"):
        print_event("plain test")
        result = subprocess.run(["plain", "test"])
        if result.returncode != 0:
            raise SystemExit(result.returncode)


@common_command
@click.command()
@click.option("--skip-test", is_flag=True, help="Skip running tests")
def check(skip_test: bool) -> None:
    """Run core validation checks"""
    run_core_checks(skip_test=skip_test)
