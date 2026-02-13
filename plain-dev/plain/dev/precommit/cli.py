from __future__ import annotations

import os
from pathlib import Path

import click

from plain.cli import register_cli
from plain.cli.check import check_short, run_core_checks
from plain.cli.runtime import without_runtime_setup


def install_git_hook() -> None:
    hook_path = os.path.join(".git", "hooks", "pre-commit")
    if os.path.exists(hook_path):
        print("pre-commit hook already exists")
    else:
        with open(hook_path, "w") as f:
            f.write(
                """#!/bin/sh
uv run plain pre-commit"""
            )
        os.chmod(hook_path, 0o755)
        print("pre-commit hook installed")


@register_cli("pre-commit")
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Git pre-commit checks"""
    # If no subcommand is provided, run the checks
    if ctx.invoked_subcommand is None:
        run_checks()


@cli.command()
@without_runtime_setup
def install() -> None:
    """Install the pre-commit git hook"""
    install_git_hook()


def run_checks() -> None:
    """Run all pre-commit checks"""

    if Path("uv.lock").exists():
        check_short("uv lock --check", "uv", "lock", "--check")

    run_core_checks(skip_test=False)

    check_short("plain build", "plain", "build")
