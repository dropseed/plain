import shutil
import subprocess
import sys
import tomllib
from importlib.metadata import entry_points
from pathlib import Path

import click

import plain.runtime
from plain.cli import register_cli
from plain.cli.print import print_event

from .compile import compile_assets, get_compiled_path


@register_cli("assets")
@click.group()
def cli() -> None:
    """Asset management"""


@cli.command()
@click.option(
    "--keep-original/--no-keep-original",
    "keep_original",
    is_flag=True,
    default=False,
    help="Keep the original assets",
)
@click.option(
    "--fingerprint/--no-fingerprint",
    "fingerprint",
    is_flag=True,
    default=True,
    help="Fingerprint the assets",
)
@click.option(
    "--compress/--no-compress",
    "compress",
    is_flag=True,
    default=True,
    help="Compress the assets",
)
def build(keep_original: bool, fingerprint: bool, compress: bool) -> None:
    """Pre-deployment build: run user commands, package build entry points, and compile assets."""

    if not keep_original and not fingerprint:
        raise click.UsageError(
            "You must either keep the original assets or fingerprint them."
        )

    # Run user-defined build commands first
    pyproject_path = plain.runtime.APP_PATH.parent / "pyproject.toml"
    if pyproject_path.exists():
        with pyproject_path.open("rb") as f:
            pyproject = tomllib.load(f)

        for name, data in (
            pyproject.get("tool", {})
            .get("plain", {})
            .get("assets", {})
            .get("build", {})
            .get("run", {})
            .items()
        ):
            print_event(f"{name}...")
            result = subprocess.run(data["cmd"], shell=True)
            if result.returncode:
                click.secho(f"Error in {name} (exit {result.returncode})", fg="red")
                sys.exit(result.returncode)

    # Then run installed package build steps (like tailwind, esbuild)
    for entry_point in entry_points(group="plain.assets.build"):
        print_event(f"{entry_point.name}...")
        entry_point.load()()

    # Compile assets
    target_dir = get_compiled_path()
    click.secho(f"Compiling assets to {target_dir}", bold=True)
    if target_dir.exists():
        click.secho("(clearing previously compiled assets)")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    total_files = 0
    total_compiled = 0

    for url_path, resolved_url_path, compiled_paths in compile_assets(
        target_dir=str(target_dir),
        keep_original=keep_original,
        fingerprint=fingerprint,
        compress=compress,
    ):
        if url_path == resolved_url_path:
            click.secho(url_path, bold=True)
        else:
            click.secho(url_path, bold=True, nl=False)
            click.secho(" → ", fg="yellow", nl=False)
            click.echo(resolved_url_path)

        print("\n".join(f"  {Path(p).relative_to(Path.cwd())}" for p in compiled_paths))

        total_files += 1
        total_compiled += len(compiled_paths)

    click.secho(
        f"\nCompiled {total_files} assets into {total_compiled} files", fg="green"
    )
