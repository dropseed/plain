"""`plain db` — manage this project's development databases.

A database is a branch of data: something you create, copy, point at, and throw
away, with a lifecycle that follows your work rather than your server. These
commands are the handle on that. The logic lives in `plain.dev.postgres`.
"""

import json as json_lib
from pathlib import Path

import click
from plain.cli import register_cli
from plain.runtime import APP_PATH

from .postgres.backends import (
    _inspect_container,
    list_managed_containers,
    remove_container,
    stop_container,
)
from .postgres.cleaning import (
    CleanItem,
    CleanPlan,
    plan_clean,
    project_checkouts,
    read_clean_facts,
)
from .postgres.cluster import Cluster
from .postgres.identity import (
    InvalidDatabaseName,
    PostgresConfig,
    clear_pointer,
    cluster_name,
    project_identity,
    read_pointer,
    resolve_database_name,
    validate_database_name,
    volume_name,
    write_pointer,
)
from .postgres.resolve import (
    clear_cached_url,
    ensure_database,
    open_cluster,
    write_cached_url,
)
from .postgres.schema_state import pending_migrations
from .state import checkout_id, find_project_root


def _project_root() -> Path:
    # Same definition `setup()` uses. The app directory is often a level below
    # the project (`example/`, `backend/`), so anchoring on it directly would
    # give this CLI a different project — and therefore a different database —
    # than the resolution that configured the app.
    return find_project_root(Path(APP_PATH).parent)


def _valid(name: str) -> str:
    """Validate a name a person typed, as a click error rather than a traceback."""
    try:
        return validate_database_name(name)
    except InvalidDatabaseName as e:
        raise click.ClickException(str(e)) from e


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
    write_cached_url(project_root, url=cluster.url(db_name))

    return project_root, cluster, project_name, db_name


def _format_size(size_bytes: int) -> str:
    return f"{size_bytes / 1024 / 1024:.1f} MB"


def _drop_named(cluster: Cluster, name: str, *, force: bool) -> None:
    """Drop the database a person named, or say what is using it."""
    from psycopg import errors

    try:
        cluster.drop_database(name, force=force)
    except errors.ObjectInUse:
        count = cluster.connection_count(name)
        open_to_it = "1 connection is" if count == 1 else f"{count} connections are"
        raise click.ClickException(
            f"{open_to_it} open to {name!r}, so it wasn't dropped. Stop what is"
            " using it (`plain dev`, a shell), or pass --force to throw it off."
        ) from None


@register_cli("db")
@click.group()
def cli() -> None:
    """Manage this project's databases — which ones exist, and which one this checkout uses."""


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def status(as_json: bool) -> None:
    """Show this checkout's database."""
    # `_open()` errors when Postgres is disabled, so handle the off-case first
    # and report it gracefully.
    config = PostgresConfig.load(_project_root())
    if config.backend == "off":
        if as_json:
            click.echo(json_lib.dumps({"backend": "off"}, indent=2))
            return
        click.secho("Backend:   off", bold=True)
        click.echo("Managed Postgres is disabled for this project.")
        return

    project_root, cluster, project_name, db_name = _open()
    source = (
        "pointer (plain db use)"
        if read_pointer(project_root)
        else "derived from directory"
    )
    exists = cluster.database_exists(db_name)
    database = (
        next(
            (d for d in cluster.list_databases(project_name) if d.name == db_name), None
        )
        if exists
        else None
    )

    pending = None
    migrations_error: str | None = None
    if exists:
        from plain.postgres.migrations.exceptions import MigrationsError

        try:
            pending = pending_migrations(cluster.url(db_name))
        except (MigrationsError, ImportError, SyntaxError) as e:
            # The planner refused the database, the files don't form a graph,
            # or one doesn't import: report it, this command only reports.
            migrations_error = str(e)

    # The container/image/volume only exist for the docker backend; a local
    # Postgres has none of them.
    container = cluster.server.container
    image = None
    if container:
        state = _inspect_container(container)
        image = state.image if state else None
    volume = volume_name(project_root) if container else None

    if as_json:
        click.echo(
            json_lib.dumps(
                {
                    "database": db_name,
                    "source": source,
                    "backend": cluster.server.backend,
                    "port": cluster.server.port,
                    "url": cluster.url(db_name),
                    "exists": exists,
                    "size_bytes": database.size_bytes if database else None,
                    "branch": database.branch if database else None,
                    "created_via": database.created_via if database else None,
                    "pending_migrations": pending.total if pending else None,
                    "pending_baselines": pending.record if pending else None,
                    "migrations_error": migrations_error,
                    "container": container,
                    "image": image,
                    "volume": volume,
                },
                indent=2,
            )
        )
        return

    click.secho(f"Database:  {db_name}", bold=True)
    click.echo(f"Source:    {source}")
    click.echo(f"Server:    {cluster.server.backend} on port {cluster.server.port}")
    click.echo(f"URL:       {cluster.url(db_name)}")
    click.echo(f"Exists:    {'yes' if exists else 'no'}")

    if exists and database:
        click.echo(f"Size:      {_format_size(database.size_bytes)}")
        if database.branch:
            click.echo(f"Branch:    {database.branch}")

    if migrations_error:
        click.secho(f"Error:     {migrations_error}", fg="red")
    elif pending and pending.total:
        parts = []
        if pending.run:
            parts.append(f"{pending.run} migration(s) not yet applied")
        if pending.record:
            parts.append(f"{pending.record} baseline(s) to record")
        click.secho(f"Pending:   {', '.join(parts)}", fg="yellow")

    if container:
        click.echo(f"Container: {container}")
        if image:
            click.echo(f"Image:     {image}")
        click.echo(f"Volume:    {volume}")


@cli.command()
def url() -> None:
    """Print this checkout's database URL, and nothing else.

    Ensures the server and database exist first, so a script can do
    `export PLAIN_POSTGRES_URL="$(plain db url)"` and rely on it being usable.
    """
    project_root, cluster, _, db_name = _open()
    ensure_database(cluster, project_root=project_root, db_name=db_name)
    click.echo(cluster.url(db_name))


@cli.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def list_(as_json: bool) -> None:
    """List this project's databases."""
    _project_root, cluster, project_name, current = _open()
    databases = cluster.list_databases(project_name)

    if as_json:
        click.echo(
            json_lib.dumps(
                [
                    {
                        "name": d.name,
                        "size_bytes": d.size_bytes,
                        "checkout": d.checkout,
                        "checkout_exists": d.checkout_exists,
                        "branch": d.branch,
                        "created_via": d.created_via,
                        "current": d.name == current,
                        "is_project_main": d.name == project_name,
                        "is_test": d.is_test,
                        "is_template": d.template_record is not None,
                    }
                    for d in databases
                ],
                indent=2,
            )
        )
        return

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
        elif database.template_record is not None:
            detail = click.style(
                f"(test template of {database.template_record.database})", dim=True
            )
        elif database.is_test:
            detail = click.style("(test)", dim=True)
        click.echo(
            f"  {database.name:<34} {_format_size(database.size_bytes):>10}  {detail}{marker}"
        )


@cli.command()
@click.argument("name", required=False)
def create(name: str | None) -> None:
    """Create an empty database (default: this checkout's name)."""
    project_root, cluster, _, db_name = _open()
    name = _valid(name) if name else db_name
    if cluster.database_exists(name):
        click.echo(f"{name!r} already exists.")
        return

    cluster.create_database(name)
    cluster.record_created(
        name,
        checkout=checkout_id(project_root) if name == db_name else None,
        created_via="create",
        project_root=project_root,
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
    dest = _valid(dest)
    source = _valid(source) if source else project_name

    if not cluster.database_exists(source):
        raise click.ClickException(f"Source database {source!r} does not exist.")
    if cluster.database_exists(dest):
        raise click.ClickException(f"Destination database {dest!r} already exists.")

    click.echo(f"Forking {source} → {dest} ...")
    try:
        mechanism = cluster.fork_database(source, dest, force=force)
    except Exception as e:
        # fork_database drops the half-copied dest before re-raising; surface
        # the reason as a clean CLI error rather than a raw traceback.
        raise click.ClickException(str(e)) from e
    cluster.record_created(
        dest,
        checkout=None,
        created_via=f"fork:{mechanism}",
        project_root=project_root,
    )
    click.secho(f"✔ Forked via {mechanism}.", fg="green")


@cli.command()
@click.argument("name", required=False)
def use(name: str | None) -> None:
    """Point this checkout at a different database (no name: back to the derived one)."""
    project_root, cluster, _, _ = _open()

    if name is None:
        if not read_pointer(project_root):
            click.echo("This checkout already uses its derived database.")
            return
        clear_pointer(project_root)
        db_name = resolve_database_name(project_root)
        write_cached_url(project_root, url=cluster.url(db_name))
        click.secho(f"✔ Back to {db_name!r}.", fg="green")
        return

    name = _valid(name)
    write_pointer(project_root, db_name=name)
    write_cached_url(project_root, url=cluster.url(name))

    click.secho(f"✔ This checkout now uses {name!r}.", fg="green")
    if not cluster.database_exists(name):
        click.secho(
            "  It doesn't exist yet — `plain db create` or `plain db fork` will make it.",
            dim=True,
        )


@cli.command()
@click.option("--yes", "-y", is_flag=True)
@click.option(
    "--force", is_flag=True, help="Throw off whatever is connected to it first."
)
def reset(yes: bool, force: bool) -> None:
    """Drop and recreate this checkout's database, empty."""
    project_root, cluster, _, db_name = _open()
    if not yes and not click.confirm(
        f"Drop and recreate {db_name!r}? All its data is lost."
    ):
        return

    _drop_named(cluster, db_name, force=force)
    cluster.create_database(db_name)
    cluster.record_created(
        db_name,
        checkout=checkout_id(project_root),
        created_via="reset",
        project_root=project_root,
    )
    click.secho(
        f"✔ Reset {db_name}. Run `plain postgres sync` to build the schema.", fg="green"
    )


@cli.command()
@click.argument("name")
@click.option("--yes", "-y", is_flag=True)
@click.option(
    "--force", is_flag=True, help="Throw off whatever is connected to it first."
)
def drop(name: str, yes: bool, force: bool) -> None:
    """Drop a database, by its name."""
    project_root, cluster, project_name, db_name = _open()
    name = _valid(name)
    if not cluster.database_exists(name):
        click.echo(f"{name!r} does not exist.")
        return

    if name == project_name:
        # Every other checkout forks from this one. Dropping it doesn't just lose
        # its data — it turns every future worktree into an empty database, which
        # is the thing this whole feature exists to avoid.
        click.secho(
            f"{name!r} is the project's main database — every new checkout is "
            "forked from it.",
            fg="yellow",
        )
        if not click.confirm("Drop it anyway?", default=False):
            return
    elif not yes and not click.confirm(f"Drop {name!r}? This cannot be undone."):
        return

    _drop_named(cluster, name, force=force)
    if name == db_name:
        # The cache would otherwise keep pointing at a database that's gone.
        clear_cached_url(project_root)
    click.secho(f"✔ Dropped {name}.", fg="green")


def _read_clean_plan(
    cluster: Cluster,
    *,
    project_root: Path,
    project_name: str,
    current: str,
    current_schema: str | None,
) -> CleanPlan:
    checkouts, in_git = project_checkouts(project_root)
    return plan_clean(
        read_clean_facts(
            cluster,
            project_name=project_name,
            current=current,
            current_schema=current_schema,
        ),
        project_main=project_name,
        current=current,
        checkouts=checkouts,
        in_git=in_git,
    )


def _current_schema() -> str | None:
    """The digest of the schema this checkout's test databases are built
    with now, which names their template. `None` when the models or the
    migration files can't be read, and then the template is left."""
    from plain.postgres.test.schema import describe_schema

    try:
        return describe_schema().hash
    except Exception:
        return None


def _echo_clean_items(items: tuple[CleanItem, ...]) -> None:
    for item in items:
        click.echo(
            f"  {item.name:<34} {_format_size(item.size_bytes):>10}  {item.owner}"
        )
        click.secho(f"      {item.reason}", dim=True)


def _drop_cleaned(
    cluster: Cluster, item: CleanItem, *, current_schema: str | None
) -> str | None:
    """Drop one database of the plan. Why it was left, if it was."""
    from psycopg import errors

    if item.is_template:
        return cluster.drop_if_a_stale_template(
            item.name,
            current_schema=current_schema,
            tested_database_is_gone=item.tested_database_is_gone,
        )
    if item.is_test:
        return cluster.drop_if_a_dead_runs(item.name)
    try:
        # Not forced: if something connected since the listing, the database
        # is somebody's.
        cluster.drop_database(item.name, force=False)
    except errors.ObjectInUse:
        return "something connected to it as it was being dropped"
    return None


@cli.command()
@click.option(
    "--dry-run",
    is_flag=True,
    help="List what would be dropped and what would be left, and drop nothing.",
)
def clean(dry_run: bool) -> None:
    """Drop the databases of checkouts that are gone, and of test runs that died.

    Every database of the project is listed first, with the reason it
    would be dropped or the reason it is left. Then it asks. There is no
    flag that skips the question: what this drops was named by nobody, and
    can't be brought back. To drop a database without being asked, name
    it: `plain db drop NAME --yes`.

    A development database is dropped only if the checkout its metadata
    names is gone, no checkout of the project is configured to use it, and
    nothing is connected to it. A test database is dropped only if it
    carries the record of the run that made it and that run is dead. The
    template a database's test runs clone is dropped only if its record
    says it is of no use now: the schema has changed since it was built,
    the database it was built for is gone, or the run building it died. The
    project's main database and this checkout's are never dropped.

    Nothing is dropped with `FORCE`, so a database something connects to
    between the listing and the drop is left.
    """
    project_root, cluster, project_name, current = _open()
    current_schema = _current_schema()
    plan = _read_clean_plan(
        cluster,
        project_root=project_root,
        project_name=project_name,
        current=current,
        current_schema=current_schema,
    )

    if plan.drop:
        reclaimed = sum(item.size_bytes for item in plan.drop)
        click.secho(
            f"Would drop {len(plan.drop)} ({_format_size(reclaimed)}):", bold=True
        )
        _echo_clean_items(plan.drop)
    else:
        click.secho("Nothing to drop.", bold=True)
    if plan.leave:
        click.echo()
        click.secho(f"Leaving {len(plan.leave)}:", bold=True)
        _echo_clean_items(plan.leave)

    if dry_run or not plan.drop:
        return

    click.echo()
    if not click.confirm(
        f'Drop the {len(plan.drop)} listed under "Would drop"? This cannot be undone.'
    ):
        return

    # The question may have waited a while for its answer. What is dropped
    # is what was listed and still qualifies now.
    still = {
        item.name
        for item in _read_clean_plan(
            cluster,
            project_root=project_root,
            project_name=project_name,
            current=current,
            current_schema=current_schema,
        ).drop
    }

    dropped = 0
    reclaimed = 0
    for item in plan.drop:
        if item.name not in still:
            click.secho(f"  Left {item.name}: it no longer qualifies.", fg="yellow")
            continue
        left_because = _drop_cleaned(cluster, item, current_schema=current_schema)
        if left_because:
            click.secho(f"  Left {item.name}: {left_because}.", fg="yellow")
            continue
        dropped += 1
        reclaimed += item.size_bytes

    click.secho(
        f"✔ Dropped {dropped}, reclaiming {_format_size(reclaimed)}.", fg="green"
    )


@cli.group()
def server() -> None:
    """Manage the Postgres server itself, not the databases on it."""


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
