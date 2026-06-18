"""Managed Postgres for `plain dev` (prototype).

plain-dev owns all the "smart" logic — Docker container lifecycle, per-checkout
database naming, and fork-by-default — then injects a normal `PLAIN_POSTGRES_URL`
so plain-postgres sees an ordinary connection string and stays unchanged.

Two layers:

- `Cluster` — thin wrapper over a running per-project Postgres container: the
  database lifecycle primitives (exists / create / drop / fork / list).
- `ensure_postgres()` — the glue called from `setup()`: ensure the container,
  resolve the per-checkout database (fork from main by default), inject the URL.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

# Local dev only — the container is bound to localhost and holds dev data.
DEV_USER = "postgres"
DEV_PASSWORD = "postgres"
DEFAULT_IMAGE = "postgres:16"
MAX_NAME_LENGTH = 63  # Postgres identifier limit


# --------------------------------------------------------------------------
# Project identity (stable across worktrees)
# --------------------------------------------------------------------------


def _sanitize(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in value.lower()).strip("_")


def _git_common_dir(cwd: Path) -> str | None:
    """The shared git dir — identical for every worktree of a repo."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return out or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def project_identity(project_root: Path) -> tuple[str, str]:
    """Return (name, hash). The hash anchors on git-common-dir so all worktrees
    of a repo share one container (required: TEMPLATE forks need one cluster)."""
    name = project_root.name
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        import tomllib

        with open(pyproject, "rb") as f:
            name = tomllib.load(f).get("project", {}).get("name", name)
    name = _sanitize(name)
    anchor = _git_common_dir(project_root) or str(project_root.resolve())
    project_hash = hashlib.sha256(anchor.encode()).hexdigest()[:8]
    return name, project_hash


def container_name(project_root: Path) -> str:
    name, project_hash = project_identity(project_root)
    return f"plain-postgres-{name}-{project_hash}"


def volume_name(project_root: Path) -> str:
    return container_name(project_root) + "-data"


def derive_db_name(project_root: Path) -> str:
    """Per-checkout database name: pointer override, else derived from the dir.

    Main checkout (dir basename == project name) → the project name as-is;
    any other checkout/worktree → `{project}_{dirbasename}`.
    """
    pointer = project_root / ".plain" / "dev" / "database"
    if pointer.exists():
        return pointer.read_text().strip()

    name, _ = project_identity(project_root)
    dir_base = _sanitize(project_root.name)
    db = name if dir_base == name else f"{name}_{dir_base}"
    if len(db) > MAX_NAME_LENGTH:
        digest = hashlib.sha256(db.encode()).hexdigest()[:8]
        db = db[: MAX_NAME_LENGTH - 9] + "_" + digest
    return db


# --------------------------------------------------------------------------
# Docker container lifecycle
# --------------------------------------------------------------------------


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check
    )


def _container_exists(name: str) -> bool:
    return bool(_docker("ps", "-aq", "-f", f"name=^{name}$").stdout.strip())


def _container_running(name: str) -> bool:
    return bool(_docker("ps", "-q", "-f", f"name=^{name}$").stdout.strip())


def _container_host_port(name: str) -> int:
    out = _docker("port", name, "5432/tcp").stdout.strip().splitlines()[0]
    return int(out.rsplit(":", 1)[1])


def ensure_container(project_root: Path, *, image: str = DEFAULT_IMAGE) -> int:
    """Ensure the per-project container is running; return its host port."""
    name = container_name(project_root)
    if not _container_exists(name):
        _docker(
            "run",
            "-d",
            "--name",
            name,
            "--restart",
            "unless-stopped",
            "-e",
            f"POSTGRES_USER={DEV_USER}",
            "-e",
            f"POSTGRES_PASSWORD={DEV_PASSWORD}",
            "-v",
            f"{volume_name(project_root)}:/var/lib/postgresql/data",
            "-p",
            "0:5432",
            image,
        )
    elif not _container_running(name):
        _docker("start", name)

    port = _container_host_port(name)
    _wait_ready(port)
    return port


def _wait_ready(port: int, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            psycopg.connect(
                host="127.0.0.1",
                port=port,
                user=DEV_USER,
                password=DEV_PASSWORD,
                dbname="postgres",
                connect_timeout=2,
            ).close()
            return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


# --------------------------------------------------------------------------
# Database lifecycle within the cluster
# --------------------------------------------------------------------------


@dataclass
class Cluster:
    """A running per-project Postgres container."""

    container: str
    port: int

    def url(self, db_name: str) -> str:
        return f"postgres://{DEV_USER}:{DEV_PASSWORD}@127.0.0.1:{self.port}/{db_name}"

    def _maint(self) -> psycopg.Connection:
        # CREATE/DROP DATABASE can't run in a transaction → autocommit on `postgres`.
        return psycopg.connect(
            host="127.0.0.1",
            port=self.port,
            user=DEV_USER,
            password=DEV_PASSWORD,
            dbname="postgres",
            autocommit=True,
        )

    def database_exists(self, name: str) -> bool:
        with self._maint() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name])
            return cur.fetchone() is not None

    def connection_count(self, name: str) -> int:
        with self._maint() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = %s", [name]
            )
            row = cur.fetchone()
            return row[0] if row else 0

    def create_database(self, name: str, *, template: str | None = None) -> None:
        stmt = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
        if template:
            stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(template)
            )
        with self._maint() as conn, conn.cursor() as cur:
            cur.execute(stmt)

    def drop_database(self, name: str) -> None:
        with self._maint() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )

    def set_comment(self, name: str, metadata: dict) -> None:
        with self._maint() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                    sql.Identifier(name), sql.Literal(json.dumps(metadata))
                )
            )

    def list_databases(self, prefix: str) -> list[tuple[str, dict | None, int]]:
        with self._maint() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT datname, shobj_description(oid, 'pg_database'), "
                "pg_database_size(datname) FROM pg_database "
                "WHERE datname LIKE %s ORDER BY datname",
                [prefix + "%"],
            )
            rows = cur.fetchall()
        return [(n, json.loads(c) if c else None, size) for n, c, size in rows]

    def get_comment(self, name: str) -> dict | None:
        with self._maint() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                "WHERE datname = %s",
                [name],
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def _terminate_connections(self, name: str) -> None:
        with self._maint() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                [name],
            )

    def fork_database(self, source: str, dest: str, *, force: bool = False) -> str:
        """Fork source→dest carrying data. Returns the mechanism used.

        Idle source → instant `CREATE DATABASE … TEMPLATE` (file copy).
        Busy source → concurrent `pg_dump | pg_restore` (no blocking), run inside
        the container so tool versions always match the server.
        `force` terminates the source's other connections and uses TEMPLATE.
        """
        busy = self.connection_count(source) > 0
        if busy and force:
            self._terminate_connections(source)
            busy = False

        if not busy:
            self.create_database(dest, template=source)
            return "template"

        self.create_database(dest)
        self._dump_restore(source, dest)
        return "dump-restore"

    def _dump_restore(self, source: str, dest: str) -> None:
        pipeline = (
            f"pg_dump -U {DEV_USER} -Fc {source} | "
            f"pg_restore -U {DEV_USER} --no-owner -d {dest}"
        )
        _docker(
            "exec",
            "-e",
            f"PGPASSWORD={DEV_PASSWORD}",
            self.container,
            "sh",
            "-c",
            pipeline,
        )


# --------------------------------------------------------------------------
# The glue: ensure + resolve + inject (called from setup())
# --------------------------------------------------------------------------


def url_already_configured() -> bool:
    """True if the user already configured a Postgres URL → opt-out.

    Env-only on purpose: this runs from `setup()` BEFORE `plain.runtime.settings`
    is configured, so touching `settings.POSTGRES_URL` here would snapshot an
    incomplete INSTALLED_PACKAGES and break app/model registration. `.env` is
    already loaded by this point, so DATABASE_URL / PLAIN_POSTGRES_URL cover the
    common cases. (Limitation: a POSTGRES_URL set only in settings.py — not env —
    isn't detected at bootstrap.)
    """
    import os

    return bool(os.environ.get("DATABASE_URL") or os.environ.get("PLAIN_POSTGRES_URL"))


def ensure_postgres(project_root: Path) -> str | None:
    """Ensure the container + this checkout's database; inject & cache the URL.

    No-op (returns None) when a URL is already configured. Otherwise returns the
    injected URL.
    """
    import os

    if url_already_configured():
        return None

    port = ensure_container(project_root)
    cluster = Cluster(container_name(project_root), port)

    project_name, _ = project_identity(project_root)
    db_name = derive_db_name(project_root)

    if not cluster.database_exists(db_name):
        # Fork from the project's main DB by default (carries seed data); fall
        # back to an empty DB when there's nothing to fork from.
        if db_name != project_name and cluster.database_exists(project_name):
            mechanism = cluster.fork_database(project_name, db_name)
        else:
            cluster.create_database(db_name)
            mechanism = "empty"
        cluster.set_comment(
            db_name,
            {"checkout": str(project_root.resolve()), "created_via": mechanism},
        )

    url = cluster.url(db_name)
    os.environ["PLAIN_POSTGRES_URL"] = url
    # Sentinel: marks that WE took over (vs. BYO). Inherited by subprocesses; the
    # dev-flow guard keys off this so it never touches a user-managed database.
    os.environ["PLAIN_DEV_MANAGED_PG"] = "1"

    cache_dir = project_root / ".plain" / "dev"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "postgres-url").write_text(url)
    return url


# --------------------------------------------------------------------------
# Shared-DB divergence guard
# --------------------------------------------------------------------------
#
# A database is "shared" when its COMMENT records a checkout other than the
# current one (you pointed here via `plain db use`). Applying a branch-only
# migration to a shared DB would mutate the database main and every other
# sharer depend on. So: shared + pending migration => protect it by forking to
# a checkout-private copy and applying there, never to the shared DB.


def db_is_shared(cluster: Cluster, db_name: str, current_checkout: str) -> bool:
    owner = (cluster.get_comment(db_name) or {}).get("checkout")
    return bool(owner) and owner != current_checkout


def pending_migration_count(url: str) -> int:
    """Number of migrations on disk not yet applied to the DB at `url`."""
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.database_url import parse_database_url
    from plain.postgres.db import _db_conn
    from plain.postgres.migrations.executor import MigrationExecutor
    from plain.postgres.sources import DirectSource

    conn = DatabaseConnection(DirectSource(parse_database_url(url)))
    # Install as the active connection: the recorder reads applied migrations via
    # `Migration.query`, which uses the global connection — not the one passed to
    # the executor. (Same reason use_test_database sets _db_conn.)
    token = _db_conn.set(conn)
    try:
        executor = MigrationExecutor(conn)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        return len(plan)
    finally:
        _db_conn.reset(token)
        conn.close()


def private_db_name(project_name: str, checkout: str) -> str:
    base = _sanitize(Path(checkout).name)
    db = project_name if base == project_name else f"{project_name}_{base}"
    if len(db) > MAX_NAME_LENGTH:
        digest = hashlib.sha256(db.encode()).hexdigest()[:8]
        db = db[: MAX_NAME_LENGTH - 9] + "_" + digest
    return db


def guard_shared_db(
    project_root: Path,
    cluster: Cluster,
    db_name: str,
    *,
    interactive: bool = True,
) -> str:
    """Protect a shared DB from a divergent migration. Returns the DB to use.

    No-op (returns db_name) unless the DB is shared AND has pending migrations.
    When it fires: interactively offer fork/apply/cancel; non-interactively
    default to forking (the safe choice for CI/agents).
    """
    import sys

    current = str(project_root.resolve())
    if not db_is_shared(cluster, db_name, current):
        return db_name
    if pending_migration_count(cluster.url(db_name)) == 0:
        return db_name  # shared, but no divergence — safe

    owner = (cluster.get_comment(db_name) or {}).get("checkout", "?")
    project_name, _ = project_identity(project_root)
    fork_name = private_db_name(project_name, current)

    choice = "f"
    if interactive and sys.stdin.isatty():
        import click

        click.secho(
            f"⚠ {db_name!r} is shared (owned by {owner}) and your branch adds "
            f"migrations not in it.",
            fg="yellow",
        )
        choice = click.prompt(
            "  [f]ork to your own copy and apply / [a]pply to the shared DB / [c]ancel",
            default="f",
        ).lower()[:1]

    if choice == "c":
        raise SystemExit("Cancelled — shared database left untouched.")
    if choice == "a":
        return db_name  # caller applies to the shared DB

    # fork-and-apply (default): copy the shared DB to a private one, repoint.
    cluster.fork_database(db_name, fork_name)
    cluster.set_comment(fork_name, {"checkout": current, "created_via": "fork:guard"})
    pointer = project_root / ".plain" / "dev" / "database"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(fork_name)
    return fork_name


def guard_dev_database(project_root: Path) -> str | None:
    """Dev-flow entry for the guard. Returns a new URL if it forked, else None.

    Only runs for OUR managed DB (PLAIN_DEV_MANAGED_PG sentinel) — never BYO.
    Safe to call unconditionally; returns None when there's nothing to do.
    """
    import os

    if os.environ.get("PLAIN_DEV_MANAGED_PG") != "1":
        return None

    port = ensure_container(project_root)
    cluster = Cluster(container_name(project_root), port)
    db_name = derive_db_name(project_root)
    new_db = guard_shared_db(project_root, cluster, db_name, interactive=True)
    return cluster.url(new_db) if new_db != db_name else None
