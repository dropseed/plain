from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import click

_BASELINE_SCRIPT = Path(__file__).with_name("_memory_baseline.py")


@click.command()
def memory() -> None:
    """Profile worker memory usage at boot.

    Shows which packages consume the most memory when a worker
    process starts — before any requests are handled.
    """
    result = subprocess.run(
        [sys.executable, str(_BASELINE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        click.secho("Failed to measure baseline:", fg="red", err=True)
        if result.stderr:
            click.echo(result.stderr, err=True)
        raise SystemExit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        click.secho("Failed to parse baseline output:", fg="red", err=True)
        click.echo(result.stdout, err=True)
        raise SystemExit(1)

    click.echo(f"Worker RSS: {data['rss']:.0f} MB ({data['modules']} modules)")
    click.echo()

    if data["packages"]:
        click.secho("Heaviest packages:", fg="yellow", bold=True)
        for pkg, size_mb in data["packages"]:
            click.echo(f"  {pkg:30s} {size_mb:>6.1f} MB")
