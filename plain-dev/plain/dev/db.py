"""`plain db` — manage per-checkout dev databases (prototype).

Operates on the project's managed Postgres container. The "smart" logic lives in
`plain.dev.postgres`; this is just the CLI surface over it.
"""

from __future__ import annotations

from pathlib import Path

import click

from plain.cli import register_cli
from plain.runtime import APP_PATH

from .postgres import (
    Cluster,
    container_name,
    derive_db_name,
    ensure_container,
    project_identity,
)


def _resolve() -> tuple[Path, Cluster, str, str]:
    """Return (project_root, cluster, project_name, db_name)."""
    project_root = Path(APP_PATH).parent
    port = ensure_container(project_root)
    cluster = Cluster(container_name(project_root), port)
    project_name, _ = project_identity(project_root)
    return project_root, cluster, project_name, derive_db_name(project_root)


@register_cli("db")
@click.group()
def cli() -> None:
    """Manage per-checkout dev databases."""


@cli.command()
def status() -> None:
    """Show this checkout's database."""
    project_root, cluster, project_name, db_name = _resolve()
    pointer = project_root / ".plain" / "dev" / "database"
    source = (
        "pointer (.plain/dev/database)"
        if pointer.exists()
        else "derived from directory"
    )
    exists = cluster.database_exists(db_name)

    click.secho(f"Database:  {db_name}", bold=True)
    click.echo(f"Source:    {source}")
    click.echo(f"Container: {cluster.container}  (port {cluster.port})")
    click.echo(f"URL:       {cluster.url(db_name)}")
    click.echo(f"Exists:    {'yes' if exists else 'no'}")
    if exists:
        size = next(
            (s for n, _, s in cluster.list_databases(db_name) if n == db_name), 0
        )
        click.echo(f"Size:      {size / 1024 / 1024:.1f} MB")


@cli.command(name="list")
def list_() -> None:
    """List all of this project's databases."""
    _, cluster, project_name, current = _resolve()
    rows = cluster.list_databases(project_name)
    if not rows:
        click.echo("No databases yet.")
        return
    for name, meta, size in rows:
        marker = "  <- current" if name == current else ""
        checkout = (meta or {}).get("checkout", "")
        click.echo(f"  {name:<32} {size / 1024 / 1024:6.1f} MB  {checkout}{marker}")


@cli.command()
@click.argument("name", required=False)
def create(name: str | None) -> None:
    """Create an empty database (default: this checkout's derived name)."""
    _, cluster, _, db_name = _resolve()
    name = name or db_name
    if cluster.database_exists(name):
        click.echo(f"{name!r} already exists.")
        return
    cluster.create_database(name)
    cluster.set_comment(name, {"checkout": "", "created_via": "create"})
    click.secho(f"✔ Created {name}.", fg="green")


@cli.command()
@click.argument("dest")
@click.option(
    "--from", "source", default=None, help="Source DB (default: project main)."
)
@click.option(
    "--force", is_flag=True, help="Terminate source connections and use TEMPLATE."
)
def fork(dest: str, source: str | None, force: bool) -> None:
    """Fork a database (carries data)."""
    _, cluster, project_name, _ = _resolve()
    source = source or project_name
    if not cluster.database_exists(source):
        raise click.ClickException(f"Source database {source!r} does not exist.")
    if cluster.database_exists(dest):
        raise click.ClickException(f"Destination database {dest!r} already exists.")
    click.echo(f"Forking {source} -> {dest} ...")
    mechanism = cluster.fork_database(source, dest, force=force)
    cluster.set_comment(dest, {"checkout": "", "created_via": f"fork:{mechanism}"})
    click.secho(f"✔ Forked via {mechanism}.", fg="green")


@cli.command()
@click.argument("name")
def use(name: str) -> None:
    """Point this checkout at a different database."""
    project_root, cluster, _, _ = _resolve()
    pointer = project_root / ".plain" / "dev" / "database"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(name)
    exists = cluster.database_exists(name)
    click.secho(f"✔ This checkout now uses {name!r}.", fg="green")
    if not exists:
        click.secho(
            "  (it doesn't exist yet — `plain db fork` or run `plain dev` to create it)",
            dim=True,
        )


@cli.command()
@click.argument("name")
@click.option("--yes", "-y", is_flag=True)
def drop(name: str, yes: bool) -> None:
    """Drop a database."""
    _, cluster, _, _ = _resolve()
    if not cluster.database_exists(name):
        click.echo(f"{name!r} does not exist.")
        return
    if not yes and not click.confirm(f"Drop {name!r}? This cannot be undone."):
        return
    cluster.drop_database(name)
    click.secho(f"✔ Dropped {name}.", fg="green")
