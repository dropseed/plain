"""Deciding whether to manage Postgres, and producing a URL when we do.

This runs from `setup()`, which happens *before* `plain.runtime.settings` is
configured — so we cannot read `settings.POSTGRES_URL` here to see whether the
user already configured one. Rather than guess, we sidestep the question with
precedence:

    PLAIN_POSTGRES_URL (env)  >  POSTGRES_URL (settings.py)  >  DATABASE_URL (env)

We inject `DATABASE_URL`, the *lowest* precedence source. So a user who sets
`POSTGRES_URL` in settings.py silently wins over us, with no detection needed
and no way for us to point their app at the wrong database. Injecting the
highest-precedence variable — as the prototype did — is what made that possible.

The asymmetry is deliberate, and it's why the two variables aren't
interchangeable here: **`PLAIN_POSTGRES_URL` is what a person sets** — explicit,
and it beats everything including us — while **`DATABASE_URL` is what we set**,
because it defers to everything. We tell users about the first and quietly use
the second. Either one being present means someone has already chosen, and we
do nothing at all.

The same property makes subprocesses cheap: `plain dev` spawns `plain postgres
sync`, which inherits our `DATABASE_URL`, sees a URL already configured, and
skips all of this. Only the outermost process does any real work.
"""

from __future__ import annotations

import os
import sys
from enum import Enum, auto
from pathlib import Path

import click

from .backends import (
    LOCAL_PORT,
    Server,
    connect_local_server,
    docker_available,
    local_available,
    local_rejected_us,
    port_is_open,
    start_docker_server,
)
from .cluster import Cluster
from .identity import (
    DEV_PASSWORD,
    DEV_USER,
    PostgresConfig,
    cluster_name,
    project_identity,
    resolve_database_name,
    volume_name,
)

# One cluster serves every worktree's connection pool plus xdist workers.
# Postgres' default of 100 is not enough; this is cheap to raise.
MAX_CONNECTIONS = 500

# Commands we won't *start a server* for. They still get a URL — see
# `ensure_postgres`; that's a separate question and a much cheaper one.
#
# A name list, not per-command metadata, because this runs before
# `plain.runtime.setup()` — the click registry that could carry such metadata
# doesn't exist yet, and building it is exactly the work this precedes.
#
# Anything not listed — including custom app commands like `create-user` — is
# assumed to want a running server, because being wrong in that direction just
# means a container we didn't strictly need, while being wrong the other way
# means a command failing to connect for no visible reason.
COMMANDS_THAT_DONT_START_A_SERVER = {
    "agent",
    "assets",
    "changelog",
    "code",
    "contrib",
    "create",
    # `plain db` manages the server explicitly — the subcommands that need one
    # open it themselves, and the ones that stop or merely report on it must
    # not start it as a side effect of `setup()`. Without this, `plain db
    # server stop` starts the container before stopping it, and the next `plain
    # db server list` silently starts it again.
    "db",
    "docs",
    "fix",
    "install",
    "scan",
    "settings",
    "tailwind",
    "tunnel",
    "upgrade",
    "urls",
    "utils",
    "vendor",
}


# The variable we write a resolved URL into. Named here rather than spelled out
# at each call site: it is deliberately the lowest-precedence source, and that
# choice has to move as one piece if it ever moves at all.
INJECTED_URL_ENV_VAR = "DATABASE_URL"


def url_already_configured() -> bool:
    """Did the user already point us at a database?

    Env-only by necessity (settings aren't loaded yet) but *sufficient*, because
    we inject the lowest-precedence variable — a settings.py URL beats ours
    without us having to detect it. See the module docstring.
    """
    return bool(
        os.environ.get(INJECTED_URL_ENV_VAR) or os.environ.get("PLAIN_POSTGRES_URL")
    )


def command_may_start_server() -> bool:
    """Should we go as far as *starting* a server for this command?

    Only consults the top-level command, so `plain run test` isn't mistaken for
    `plain test`.
    """
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not argv:
        return False  # bare `plain` / `plain --help`
    return argv[0] not in COMMANDS_THAT_DONT_START_A_SERVER


def cache_path(project_root: Path) -> Path:
    return project_root / ".plain" / "dev" / "postgres-url"


class CachedURL(Enum):
    """What we learned about the URL we cached last time."""

    MISSING = auto()  # nothing cached yet
    UNREACHABLE = auto()  # cached, but no server is answering
    NO_DATABASE = auto()  # server is up, but our database is gone
    OK = auto()


def read_cached_url(project_root: Path) -> tuple[CachedURL, str | None]:
    """Check the cached URL by actually connecting to it.

    Verified with a real connection rather than a Docker call — ~6ms versus
    ~80ms — which is what makes it affordable on every command. That's more
    than a bare TCP probe would cost, and worth it: the probe can only tell us
    something is listening, while a connection distinguishes "the server is
    gone" from "the server is fine but our database was dropped". The second
    case is repairable without Docker at all, and repairing it beats handing
    the app a URL that will hang for the pool's full timeout.
    """
    cache = cache_path(project_root)
    if not cache.exists():
        return CachedURL.MISSING, None

    url = cache.read_text().strip()
    if not url:
        return CachedURL.MISSING, None

    port = _port_from_url(url)
    if port is None or not port_is_open(port):
        # Cheap pre-check so a dead server costs 0.2ms, not a connect timeout.
        return CachedURL.UNREACHABLE, url

    import psycopg

    try:
        psycopg.connect(url, connect_timeout=2).close()
    except psycopg.errors.InvalidCatalogName:
        return CachedURL.NO_DATABASE, url
    except psycopg.OperationalError:
        return CachedURL.UNREACHABLE, url

    return CachedURL.OK, url


def write_cached_url(project_root: Path, *, url: str) -> None:
    cache = cache_path(project_root)
    if cache.exists() and cache.read_text() == url:
        return  # Repair is an event; the common case shouldn't touch disk.
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(url)


def clear_cached_url(project_root: Path) -> None:
    """Drop the cache — for when the database it names no longer exists."""
    cache_path(project_root).unlink(missing_ok=True)


def _port_from_url(url: str) -> int | None:
    from urllib.parse import urlsplit

    try:
        return urlsplit(url).port
    except ValueError:
        return None


def start_server(project_root: Path, *, config: PostgresConfig) -> Server | None:
    """Bring up (or find) the project's Postgres server.

    `config.backend` is the *preference* — usually `"auto"` — so the selection
    order here is what turns it into an answer. Returns `None` when no backend
    is available, having already explained why.
    """
    if config.backend == "off":
        return None

    if config.backend in ("auto", "docker") and docker_available():
        return start_docker_server(
            container=cluster_name(project_root),
            volume=volume_name(project_root),
            image=config.image,
            max_connections=MAX_CONNECTIONS,
        )

    if config.backend in ("auto", "local") and local_available():
        return connect_local_server()

    _explain_no_backend(config.backend)
    return None


def _explain_no_backend(backend: str) -> None:
    if local_rejected_us():
        # The most common workstation case, and the most confusing one: you do
        # have Postgres, so "no Postgres available" reads as a lie. Homebrew and
        # Postgres.app both create a superuser named after your OS account and
        # no `postgres` role, which is exactly what we tried to log in as.
        click.secho(
            f"A Postgres is listening on 127.0.0.1:{LOCAL_PORT}, but it rejected "
            f"the {DEV_USER!r} login we use.",
            fg="yellow",
            err=True,
        )
        click.echo(
            "  Homebrew and Postgres.app name the superuser after your account "
            "rather than 'postgres'. Point us at it directly:\n"
            f"    export PLAIN_POSTGRES_URL=postgres://$USER@127.0.0.1:{LOCAL_PORT}/<database>\n"
            "  Or start Docker and we'll run our own, isolated from it.",
            err=True,
        )
        return

    if backend == "docker":
        message = "Docker isn't available, and postgres backend is pinned to 'docker'."
    elif backend == "local":
        message = (
            f"No Postgres listening on 127.0.0.1:{LOCAL_PORT}, and postgres "
            "backend is pinned to 'local'."
        )
    else:
        message = (
            "No Postgres available: Docker isn't running and nothing is "
            f"listening on 127.0.0.1:{LOCAL_PORT}."
        )
    click.secho(
        f"{message}\nSet PLAIN_POSTGRES_URL to use your own database, or start Docker.",
        fg="yellow",
        err=True,
    )


def ensure_database(cluster: Cluster, *, project_root: Path, db_name: str) -> None:
    """Make sure this checkout's database exists, forking from main if we can.

    A new worktree starting empty is the actual pain point in parallel dev —
    you have to re-seed it every time. So the default is a copy of the project's
    main database, which carries its data. `plain db create` opts out.
    """
    if cluster.database_exists(db_name):
        return

    project_name, _ = project_identity(project_root)
    fork_source = project_name if db_name != project_name else None

    # Two processes can reach this at once — several worktrees starting
    # together, or `plain test` and `plain shell` side by side. Both see the
    # database missing, both create it, and one loses. Losing that race means
    # the database now exists, which is all we wanted, so treat it as success
    # rather than crashing the command.
    from psycopg import errors

    try:
        if fork_source and cluster.database_exists(fork_source):
            mechanism = cluster.fork_database(fork_source, db_name)
            click.secho(
                f"Created database {db_name!r} from {fork_source!r} ({mechanism}).",
                fg="green",
                err=True,
            )
        else:
            cluster.create_database(db_name)
            mechanism = "empty"
            click.secho(f"Created database {db_name!r}.", fg="green", err=True)
    except (errors.DuplicateDatabase, errors.UniqueViolation):
        return

    cluster.record_created(
        db_name,
        checkout=str(project_root.resolve()),
        created_via=mechanism,
        project_root=project_root,
    )


def open_cluster(project_root: Path, *, create: bool = True) -> Cluster | None:
    """The project's cluster, starting a server if needed and allowed."""
    config = PostgresConfig.load(project_root)
    if config.backend == "off":
        return None

    if not create:
        # Reachable server only — callers here are advisory (the guard, the
        # branch check) and must never start Docker as a side effect.
        status, cached = read_cached_url(project_root)
        if cached is None or status is CachedURL.UNREACHABLE:
            return None
        return Cluster(_server_from_url(cached))

    server = start_server(project_root, config=config)
    return Cluster(server) if server else None


def _server_from_url(url: str) -> Server:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return Server(
        host=parts.hostname or "127.0.0.1",
        port=parts.port or 5432,
        user=parts.username or DEV_USER,
        password=parts.password or DEV_PASSWORD,
        backend="cached",
    )


def ensure_postgres(project_root: Path) -> str | None:
    """Resolve a database URL for this checkout and inject it. Returns the URL.

    Returns `None` — changing nothing — when the user configured their own
    database, when managed Postgres is switched off, or when this command
    doesn't need a database and nothing is running yet.
    """
    if url_already_configured():
        return None

    config = PostgresConfig.load(project_root)
    if config.backend == "off":
        return None

    status, cached = read_cached_url(project_root)

    # Fast path: the database we used last time is still there. No Docker.
    if status is CachedURL.OK and cached:
        _inject(cached)
        return cached

    # The server is fine but our database went away — someone dropped it, or
    # another checkout cleaned up. Rebuild it in place; still no Docker needed.
    if status is CachedURL.NO_DATABASE and cached:
        cluster = Cluster(_server_from_url(cached))
        db_name = resolve_database_name(project_root)
        ensure_database(cluster, project_root=project_root, db_name=db_name)
        # Rebuild the URL from the resolved name rather than reusing the cached
        # one: the cache may predate a pointer change or a renamed worktree, so
        # it can name a database we didn't just create. Rewrite the cache too.
        url = cluster.url(db_name)
        _inject(url)
        write_cached_url(project_root, url=url)
        return url

    if not command_may_start_server():
        # We won't start a server for this command — but that's a question about
        # side effects, not about which database this checkout owns. `POSTGRES_URL`
        # is a required setting, so refusing to answer here left the app unable to
        # configure at all: with the server stopped, `plain docs` and `plain fix`
        # failed outright, and with no cache yet *every* `plain db` command failed
        # — including the ones whose whole job is to fix that.
        #
        # So always answer. The URL names this checkout's database correctly, and
        # nothing connects unless the command connects. `plain db` goes on to open
        # the cluster itself, which starts the server and rewrites the cache.
        url = cached or _unstarted_url(project_root)
        _inject(url)
        return url

    server = start_server(project_root, config=config)
    if server is None:
        return None

    cluster = Cluster(server)
    db_name = resolve_database_name(project_root)
    ensure_database(cluster, project_root=project_root, db_name=db_name)

    url = cluster.url(db_name)
    _inject(url)
    write_cached_url(project_root, url=url)
    return url


def _unstarted_url(project_root: Path) -> str:
    """A URL for this checkout when we haven't started a server to ask.

    The database name is exact — it's derived, not looked up. The host and port
    are a guess at the conventional local Postgres, because a stopped container
    publishes no port and finding out would mean starting it, which is the one
    thing this path exists to avoid.

    So this is honest rather than authoritative: right for the local backend,
    and for Docker it names the right database on a port that isn't listening.
    That is exactly the contract every command on this path already had with a
    stale cache, and it can't reach another project's data — the name is
    namespaced per project and per checkout.

    Deliberately not cached: the cache is for URLs we've confirmed.
    """
    return connect_local_server().url(resolve_database_name(project_root))


def _inject(url: str) -> None:
    # The lowest-precedence source, so a settings.py POSTGRES_URL still wins.
    # Subprocesses inherit it and skip resolution entirely.
    os.environ[INJECTED_URL_ENV_VAR] = url


def is_managed(project_root: Path) -> bool:
    """Is the database currently in use one that we produced?

    Answered by comparing the active URL against what we cached, rather than a
    sentinel environment variable. A `PLAIN_`-prefixed sentinel would be read as
    a misspelled setting by the `settings.unused_env_vars` preflight check, and
    putting a permanent warning in every managed project to answer a question we
    can already answer from a file isn't a trade worth making.

    Only a database we created can match, so a bring-your-own URL never does —
    which is what the guard and the branch check rely on before acting.
    """
    active = os.environ.get(INJECTED_URL_ENV_VAR)
    if not active:
        return False

    cache = cache_path(project_root)
    return cache.exists() and cache.read_text().strip() == active
