"""`plain db` — manage this project's development databases.

A database is a branch of data: something you create, copy, point at, and throw
away, with a lifecycle that follows your work rather than your server. These
commands are the handle on that. The logic lives in `plain.dev.postgres`.
"""

from __future__ import annotations

from pathlib import Path

import click

from plain.cli import register_cli
from plain.runtime import APP_PATH

from .postgres import (
    Cluster,
    DevDatabase,
    current_branch,
    ensure_database,
    open_cluster,
    project_identity,
    read_pointer,
    resolve_database_name,
    write_cached_url,
    write_pointer,
)
from .postgres.backends import (
    list_managed_containers,
    remove_container,
    stop_container,
)
from .postgres.identity import PostgresConfig, clear_pointer, cluster_name, volume_name
from .postgres.schema_state import pending_migration_count


def _project_root() -> Path:
    return Path(APP_PATH).parent


def _open() -> tuple[Path, Cluster, str, str]:
    """Return (project_root, cluster, project_name, this checkout's db name)."""
    project_root = _project_root()
    cluster = open_cluster(project_root)
    if cluster is None:
        raise click.ClickException(
            "No managed Postgres available. Start Docker, run a local Postgres, "
            "or set PLAIN_POSTGRES_URL to use your own."
        )
    project_name, _ = project_identity(project_root)
    db_name = resolve_database_name(project_root)

    # These commands always talk to the real server, so they're also the place
    # a stale cache gets repaired — the TCP probe can tell that *a* server is
    # listening, but not that it's still the right one (a project's cluster
    # identity moves if its git identity does).
    write_cached_url(project_root, cluster.url(db_name))

    return project_root, cluster, project_name, db_name


def _format_size(size_bytes: int) -> str:
    return f"{size_bytes / 1024 / 1024:.1f} MB"


@register_cli("db")
@click.group()
def cli() -> None:
    """Manage development databases."""


@cli.command()
def status() -> None:
    """Show this checkout's database."""
    project_root, cluster, _, db_name = _open()
    source = (
        "pointer (.plain/dev/database)"
        if read_pointer(project_root)
        else "derived from directory"
    )
    exists = cluster.database_exists(db_name)

    click.secho(f"Database:  {db_name}", bold=True)
    click.echo(f"Source:    {source}")
    click.echo(f"Server:    {cluster.server.backend} on port {cluster.server.port}")
    click.echo(f"URL:       {cluster.url(db_name)}")
    click.echo(f"Exists:    {'yes' if exists else 'no'}")

    if not exists:
        return

    database = next(
        (d for d in cluster.list_databases(db_name) if d.name == db_name), None
    )
    if database:
        click.echo(f"Size:      {_format_size(database.size_bytes)}")
        if database.branch:
            click.echo(f"Branch:    {database.branch}")

    pending = pending_migration_count(cluster.url(db_name))
    if pending:
        click.secho(f"Pending:   {pending} migration(s) not yet applied", fg="yellow")


@cli.command()
def url() -> None:
    """Print this checkout's database URL, and nothing else.

    Ensures the server and database exist first, so a script can do
    `export PLAIN_POSTGRES_URL="$(plain db url)"` and rely on it being usable.
    """
    project_root, cluster, _, db_name = _open()
    ensure_database(cluster, project_root, db_name)
    click.echo(cluster.url(db_name))


@cli.command(name="list")
def list_() -> None:
    """List this project's databases."""
    project_root, cluster, project_name, current = _open()
    databases = cluster.list_databases(project_name)
    if not databases:
        click.echo("No databases yet.")
        return

    for database in databases:
        marker = (
            click.style("  <- current", fg="green") if database.name == current else ""
        )
        detail = database.checkout or ""
        if database.checkout and not database.checkout_exists:
            detail = click.style(f"{database.checkout} (gone)", fg="yellow")
        click.echo(
            f"  {database.name:<34} {_format_size(database.size_bytes):>10}  {detail}{marker}"
        )


@cli.command()
@click.argument("name", required=False)
def create(name: str | None) -> None:
    """Create an empty database (default: this checkout's name)."""
    project_root, cluster, _, db_name = _open()
    name = name or db_name
    if cluster.database_exists(name):
        click.echo(f"{name!r} already exists.")
        return

    cluster.create_database(name)
    cluster.set_metadata(
        name,
        {
            "checkout": str(project_root.resolve()) if name == db_name else None,
            "branch": current_branch(project_root),
            "created_via": "create",
        },
    )
    click.secho(f"✔ Created {name}.", fg="green")


@cli.command()
@click.argument("dest")
@click.option(
    "--from", "source", default=None, help="Source database (default: project main)."
)
@click.option(
    "--force", is_flag=True, help="Terminate source connections and use TEMPLATE."
)
def fork(dest: str, source: str | None, force: bool) -> None:
    """Copy a database, data and all."""
    project_root, cluster, project_name, _ = _open()
    source = source or project_name

    if not cluster.database_exists(source):
        raise click.ClickException(f"Source database {source!r} does not exist.")
    if cluster.database_exists(dest):
        raise click.ClickException(f"Destination database {dest!r} already exists.")

    click.echo(f"Forking {source} → {dest} ...")
    mechanism = cluster.fork_database(source, dest, force=force)
    cluster.set_metadata(
        dest,
        {
            "checkout": None,
            "branch": current_branch(project_root),
            "created_via": f"fork:{mechanism}",
        },
    )
    click.secho(f"✔ Forked via {mechanism}.", fg="green")


@cli.command()
@click.argument("name")
def use(name: str) -> None:
    """Point this checkout at a different database."""
    project_root, cluster, _, _ = _open()
    write_pointer(project_root, name)
    write_cached_url(project_root, cluster.url(name))

    click.secho(f"✔ This checkout now uses {name!r}.", fg="green")
    if not cluster.database_exists(name):
        click.secho(
            "  It doesn't exist yet — `plain db create` or `plain db fork` will make it.",
            dim=True,
        )


@cli.command()
def unuse() -> None:
    """Go back to this checkout's derived database name."""
    project_root, cluster, project_name, _ = _open()
    if not read_pointer(project_root):
        click.echo("This checkout already uses its derived database.")
        return

    clear_pointer(project_root)
    db_name = resolve_database_name(project_root)
    write_cached_url(project_root, cluster.url(db_name))
    click.secho(f"✔ Back to {db_name!r}.", fg="green")


@cli.command()
@click.option("--yes", "-y", is_flag=True)
def reset(yes: bool) -> None:
    """Drop and recreate this checkout's database, empty."""
    project_root, cluster, _, db_name = _open()
    if not yes and not click.confirm(
        f"Drop and recreate {db_name!r}? All its data is lost."
    ):
        return

    cluster.drop_database(db_name)
    cluster.create_database(db_name)
    cluster.set_metadata(
        db_name,
        {
            "checkout": str(project_root.resolve()),
            "branch": current_branch(project_root),
            "created_via": "reset",
        },
    )
    click.secho(
        f"✔ Reset {db_name}. Run `plain postgres sync` to build the schema.", fg="green"
    )


@cli.command()
@click.argument("name")
@click.option("--yes", "-y", is_flag=True)
def drop(name: str, yes: bool) -> None:
    """Drop a database."""
    project_root, cluster, _, db_name = _open()
    if not cluster.database_exists(name):
        click.echo(f"{name!r} does not exist.")
        return
    if not yes and not click.confirm(f"Drop {name!r}? This cannot be undone."):
        return

    cluster.drop_database(name)
    if name == db_name:
        # The cache would otherwise keep pointing at a database that's gone.
        (project_root / ".plain" / "dev" / "postgres-url").unlink(missing_ok=True)
    click.secho(f"✔ Dropped {name}.", fg="green")


@cli.command()
@click.option("--yes", "-y", is_flag=True)
def clean(yes: bool) -> None:
    """Drop databases whose checkout directory no longer exists.

    Forking is a full copy, so deleted worktrees leave real disk behind. This
    only ever removes databases that recorded a checkout path *and* whose path
    is now gone — a database with no recorded owner is left alone.
    """
    project_root, cluster, project_name, current = _open()

    orphans: list[DevDatabase] = [
        database
        for database in cluster.list_databases(project_name)
        if database.checkout
        and not database.checkout_exists
        and database.name != current
    ]
    if not orphans:
        click.echo("Nothing to clean.")
        return

    reclaimed = sum(d.size_bytes for d in orphans)
    click.echo(f"Orphaned databases ({_format_size(reclaimed)} total):")
    for database in orphans:
        click.echo(
            f"  {database.name:<34} {_format_size(database.size_bytes):>10}  {database.checkout}"
        )

    if not yes and not click.confirm("Drop these?"):
        return

    for database in orphans:
        cluster.drop_database(database.name)
    click.secho(
        f"✔ Dropped {len(orphans)}, reclaiming {_format_size(reclaimed)}.", fg="green"
    )


@cli.group()
def server() -> None:
    """Manage the Postgres server itself, not the databases on it."""


@server.command(name="status")
def server_status() -> None:
    """Show this project's Postgres server."""
    project_root = _project_root()
    container = cluster_name(project_root)
    config = PostgresConfig.load(project_root)

    click.secho(f"Backend:   {config.backend}", bold=True)
    if config.backend == "local":
        click.echo("Server:    local Postgres on 127.0.0.1:5432 (not managed by us)")
        return

    match = next((c for c in list_managed_containers() if c.name == container), None)
    if match is None:
        click.echo(f"Container: {container} (not created yet)")
        return

    click.echo(f"Container: {match.name}")
    click.echo(f"State:     {'running' if match.running else 'stopped'}")
    click.echo(f"Image:     {match.image}")
    click.echo(f"Volume:    {volume_name(project_root)}")


@server.command(name="list")
def server_list() -> None:
    """List every plain-dev Postgres container on this machine.

    One per project, created on demand and never removed automatically. This is
    how you find the ones you've stopped needing.
    """
    containers = list_managed_containers()
    if not containers:
        click.echo("No managed Postgres containers.")
        return

    current = cluster_name(_project_root())
    running = sum(1 for c in containers if c.running)

    for container in containers:
        state = (
            click.style("running", fg="green")
            if container.running
            else click.style("stopped", dim=True)
        )
        marker = (
            click.style("  <- this project", fg="green")
            if container.name == current
            else ""
        )
        click.echo(f"  {container.name:<44} {state}  {container.image}{marker}")

    click.echo(f"\n{len(containers)} container(s), {running} running.")
    if running > 1:
        click.secho(
            "Each running server holds memory even when idle — "
            "`plain db server stop` in a project you're done with.",
            dim=True,
        )


@server.command(name="stop")
def server_stop() -> None:
    """Stop this project's Postgres server.

    Safe: the data volume is untouched, and the next command that needs a
    database starts it again.
    """
    container = cluster_name(_project_root())
    if stop_container(container):
        click.secho(f"✔ Stopped {container}.", fg="green")
    else:
        click.echo(f"{container} isn't running.")


@server.command(name="remove")
@click.option(
    "--keep-data", is_flag=True, help="Remove the container but keep the volume."
)
@click.option("--yes", "-y", is_flag=True)
def server_remove(keep_data: bool, yes: bool) -> None:
    """Remove this project's Postgres server, and its data by default."""
    project_root = _project_root()
    container = cluster_name(project_root)
    volume = None if keep_data else volume_name(project_root)

    warning = (
        f"Remove {container}?"
        if keep_data
        else f"Remove {container} AND every database on it? This cannot be undone."
    )
    if not yes and not click.confirm(warning):
        return

    remove_container(container, volume=volume)
    click.secho(f"✔ Removed {container}.", fg="green")
    if keep_data:
        click.secho(
            f"  Volume {volume_name(project_root)} kept; the next run reuses it.",
            dim=True,
        )
