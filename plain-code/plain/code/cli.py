from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import click

from plain.cli import register_cli
from plain.cli.print import print_event
from plain.cli.runtime import common_command, without_runtime_setup

from .annotations import AnnotationResult, check_annotations
from .biome import Biome

DEFAULT_RUFF_CONFIG = Path(__file__).parent / "ruff_defaults.toml"


@without_runtime_setup
@register_cli("code")
@click.group()
def cli() -> None:
    """Code formatting and linting"""
    pass


@without_runtime_setup
@cli.command()
@click.option("--force", is_flag=True, help="Reinstall even if up to date")
@click.pass_context
def install(ctx: click.Context, force: bool) -> None:
    """Install or update Biome binary"""
    config = get_code_config()

    if not config.get("biome", {}).get("enabled", True):
        click.secho("Biome is disabled in configuration", fg="yellow")
        return

    biome = Biome()

    if force or not biome.is_installed() or biome.needs_update():
        version_to_install = config.get("biome", {}).get("version", "")
        if version_to_install:
            click.secho(
                f"Installing Biome standalone version {version_to_install}...",
                bold=True,
                nl=False,
            )
            installed = biome.install(version_to_install)
            click.secho(f"Biome {installed} installed", fg="green")
        else:
            ctx.invoke(update)
    else:
        click.secho("Biome already installed", fg="green")


@without_runtime_setup
@cli.command()
def update() -> None:
    """Update Biome to latest version"""
    config = get_code_config()

    if not config.get("biome", {}).get("enabled", True):
        click.secho("Biome is disabled in configuration", fg="yellow")
        return

    biome = Biome()
    click.secho("Updating Biome standalone...", bold=True)
    version = biome.install()
    click.secho(f"Biome {version} installed", fg="green")


@without_runtime_setup
@cli.command()
@click.pass_context
@click.argument("path", default=".")
@click.option("--skip-ruff", is_flag=True, help="Skip Ruff checks")
@click.option("--skip-ty", is_flag=True, help="Skip ty type checks")
@click.option("--skip-biome", is_flag=True, help="Skip Biome checks")
@click.option("--skip-annotations", is_flag=True, help="Skip type annotation checks")
def check(
    ctx: click.Context,
    path: str,
    skip_ruff: bool,
    skip_ty: bool,
    skip_biome: bool,
    skip_annotations: bool,
) -> None:
    """Check for formatting and linting issues"""
    ruff_args = ["--config", str(DEFAULT_RUFF_CONFIG)]
    config = get_code_config()

    for e in config.get("exclude", []):
        ruff_args.extend(["--exclude", e])

    def maybe_exit(return_code: int) -> None:
        if return_code != 0:
            click.secho(
                "\nCode check failed. Run `plain fix` and/or fix issues manually.",
                fg="red",
                err=True,
            )
            sys.exit(return_code)

    if not skip_ruff:
        print_event("ruff check...", newline=False)
        result = subprocess.run(["ruff", "check", path, *ruff_args])
        maybe_exit(result.returncode)

        print_event("ruff format --check...", newline=False)
        result = subprocess.run(["ruff", "format", path, "--check", *ruff_args])
        maybe_exit(result.returncode)

    if not skip_ty and config.get("ty", {}).get("enabled", True):
        print_event("ty check...", newline=False)
        ty_args = ["ty", "check", path, "--no-progress"]
        for e in config.get("exclude", []):
            ty_args.extend(["--exclude", e])
        result = subprocess.run(ty_args)
        maybe_exit(result.returncode)

    if not skip_biome and config.get("biome", {}).get("enabled", True):
        biome = Biome()

        if biome.needs_update():
            ctx.invoke(install)

        print_event("biome check...", newline=False)
        result = biome.invoke("check", path)
        maybe_exit(result.returncode)

    if not skip_annotations and config.get("annotations", {}).get("enabled", True):
        print_event("annotations...", newline=False)
        # Combine top-level exclude with annotation-specific exclude
        exclude_patterns = list(config.get("exclude", []))
        exclude_patterns.extend(config.get("annotations", {}).get("exclude", []))
        ann_result = check_annotations(path, exclude_patterns or None)
        if ann_result.missing_count > 0:
            click.secho(
                f"{ann_result.missing_count} functions are untyped",
                fg="red",
            )
            click.secho("Run 'plain code annotations --details' for details")
            maybe_exit(1)
        else:
            click.secho("All functions typed!", fg="green")


@without_runtime_setup
@cli.command()
@click.argument("path", default=".")
@click.option("--details", is_flag=True, help="List untyped functions")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def annotations(path: str, details: bool, as_json: bool) -> None:
    """Check type annotation status"""
    config = get_code_config()
    # Combine top-level exclude with annotation-specific exclude
    exclude_patterns = list(config.get("exclude", []))
    exclude_patterns.extend(config.get("annotations", {}).get("exclude", []))
    result = check_annotations(path, exclude_patterns or None)
    if as_json:
        _print_annotations_json(result)
    else:
        _print_annotations_report(result, show_details=details)


def _print_annotations_report(
    result: AnnotationResult,
    show_details: bool = False,
) -> None:
    """Print the annotation report with colors."""
    if result.total_functions == 0:
        click.echo("No functions found")
        return

    # Detailed output first (if enabled and there are untyped functions)
    if show_details and result.missing_count > 0:
        # Collect all untyped functions with full paths
        untyped_items: list[tuple[str, str, int, list[str]]] = []

        for stats in result.file_stats:
            for func in stats.functions:
                if not func.is_fully_typed:
                    issues = []
                    if not func.has_return_type:
                        issues.append("return type")
                    missing_params = func.total_params - func.typed_params
                    if missing_params > 0:
                        param_word = "param" if missing_params == 1 else "params"
                        issues.append(f"{missing_params} {param_word}")
                    untyped_items.append((stats.path, func.name, func.line, issues))

        # Sort by file path, then line number
        untyped_items.sort(key=lambda x: (x[0], x[2]))

        # Print each untyped function
        for file_path, func_name, line, issues in untyped_items:
            location = click.style(f"{file_path}:{line}", fg="cyan")
            issue_str = click.style(f"({', '.join(issues)})", dim=True)
            click.echo(f"{location}  {func_name}  {issue_str}")

        click.echo()

    # Summary line
    pct = result.coverage_percentage
    color = "green" if result.missing_count == 0 else "red"
    click.secho(
        f"{pct:.1f}% typed ({result.fully_typed_functions}/{result.total_functions} functions)",
        fg=color,
    )

    # Code smell indicators (only if present)
    smells = []
    if result.total_ignores > 0:
        smells.append(f"{result.total_ignores} ignore")
    if result.total_casts > 0:
        smells.append(f"{result.total_casts} cast")
    if result.total_asserts > 0:
        smells.append(f"{result.total_asserts} assert")
    if smells:
        click.secho(f"{', '.join(smells)}", fg="yellow")


def _print_annotations_json(result: AnnotationResult) -> None:
    """Print the annotation report as JSON."""
    output = {
        "overall_coverage": result.coverage_percentage,
        "total_functions": result.total_functions,
        "fully_typed_functions": result.fully_typed_functions,
        "total_ignores": result.total_ignores,
        "total_casts": result.total_casts,
        "total_asserts": result.total_asserts,
    }
    click.echo(json.dumps(output))


@common_command
@without_runtime_setup
@register_cli("fix", shortcut_for="code fix")
@cli.command()
@click.pass_context
@click.argument("path", default=".")
@click.option("--unsafe-fixes", is_flag=True, help="Apply ruff unsafe fixes")
@click.option("--add-noqa", is_flag=True, help="Add noqa comments to suppress errors")
def fix(ctx: click.Context, path: str, unsafe_fixes: bool, add_noqa: bool) -> None:
    """Fix formatting and linting issues"""
    ruff_args = ["--config", str(DEFAULT_RUFF_CONFIG)]
    config = get_code_config()

    for e in config.get("exclude", []):
        ruff_args.extend(["--exclude", e])

    if unsafe_fixes and add_noqa:
        raise click.UsageError("Cannot use both --unsafe-fixes and --add-noqa")

    if unsafe_fixes:
        print_event("ruff check --fix --unsafe-fixes...", newline=False)
        result = subprocess.run(
            ["ruff", "check", path, "--fix", "--unsafe-fixes", *ruff_args]
        )
    elif add_noqa:
        print_event("ruff check --add-noqa...", newline=False)
        result = subprocess.run(["ruff", "check", path, "--add-noqa", *ruff_args])
    else:
        print_event("ruff check --fix...", newline=False)
        result = subprocess.run(["ruff", "check", path, "--fix", *ruff_args])

    if result.returncode != 0:
        sys.exit(result.returncode)

    print_event("ruff format...", newline=False)
    result = subprocess.run(["ruff", "format", path, *ruff_args])
    if result.returncode != 0:
        sys.exit(result.returncode)

    if config.get("biome", {}).get("enabled", True):
        biome = Biome()

        if biome.needs_update():
            ctx.invoke(install)

        args = ["check", path, "--write"]

        if unsafe_fixes:
            args.append("--unsafe")
            print_event("biome check --write --unsafe...", newline=False)
        else:
            print_event("biome check --write...", newline=False)

        result = biome.invoke(*args)

        if result.returncode != 0:
            sys.exit(result.returncode)


def get_code_config() -> dict[str, Any]:
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return {}
    with pyproject.open("rb") as f:
        return tomllib.load(f).get("tool", {}).get("plain", {}).get("code", {})
