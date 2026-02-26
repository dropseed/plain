from __future__ import annotations

import re
from pathlib import Path

import click

from plain.cli import register_cli


@register_cli("admin")
@click.group("admin")
def admin_cli() -> None:
    """Admin tools"""


@admin_cli.command("icons")
@click.argument("query", required=False)
def icons(query: str | None) -> None:
    """Search available admin icons (Bootstrap Icons)"""
    css_path = (
        Path(__file__).parent
        / "assets"
        / "admin"
        / "vendor"
        / "bootstrap-icons.min.css"
    )
    css = css_path.read_text()
    names = re.findall(r"\.bi-([a-z0-9][a-z0-9-]*)::before", css)

    if query:
        query_lower = query.lower()
        names = [n for n in names if query_lower in n]

    if not names:
        click.echo("No icons found.")
        return

    for name in names:
        click.echo(name)

    if query:
        click.echo(f"\n{len(names)} icons found")
    else:
        click.echo(f"\n{len(names)} icons available")
