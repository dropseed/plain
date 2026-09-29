"""
The databases a test run uses, and how the run is pointed at them.

A run has databases of its own, named for the checkout's database and for
the run:

    test_<database>_r<pid>                   the rolled-back tests share it
    test_<database>_r<pid>_<test name>       one `@isolated_db` test's

So any number of runs in one checkout, at the same moment, each create,
use and drop their own. A run that ends drops its databases. One that was
killed leaves them, and the next run in that checkout removes them.

**Which runs are alive.** For as long as it lives, a run holds a session
advisory lock on the `postgres` maintenance database, keyed by the name of
its shared database. Postgres releases the lock when the run's connection
goes, however the run ended. A database is a dead run's when nobody holds
the lock its name says its run would hold. That is settled by asking for
the lock, so a run is never mistaken for dead in the moment between
creating a database and connecting to it.

**Where a connection goes.** While a test database is in use,
`POSTGRES_URL` *is* that database: the setting is changed, and the pool is
rebuilt on it. The test gets a connection of its own through the
connection `ContextVar`, as before. Anything else that asks for a
connection the ordinary way (a thread the code under test started has an
empty context, so `get_connection()` makes it a new one) gets one from
the pool, to the test database. Nothing in the run can reach the
development database by asking. `POSTGRES_MANAGEMENT_URL`, if set, is
pointed at the test database too.
"""

import hashlib
import os
import re
import secrets
import sys
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from plain.postgres.connection import DatabaseConnection
from plain.postgres.database_url import (
    DatabaseConfig,
    parse_database_url,
    replace_database_name,
)
from plain.postgres.databases import (
    connection_count,
    create_database,
    drop_database,
)
from plain.postgres.db import _db_conn
from plain.postgres.dialect import MAX_NAME_LENGTH
from plain.postgres.migrations.executor import MigrationExecutor
from plain.postgres.sources import (
    DirectSource,
    build_connection_params,
    runtime_pool_source,
)
from plain.postgres.utils import names_digest
from plain.runtime import settings
from psycopg import errors

TEST_DATABASE_PREFIX = "test_"

# `r` and the process id of the run. When another live run already holds
# that name (the same process id on another machine, on one server), `x`
# and four random hex digits follow.
_RUN_TOKEN = re.compile(r"_r[0-9]+(?:x[0-9a-f]+)?(?=_|$)")

# The digest that ends a name that had to be cut to fit, and the `_` before it.
_DIGEST_LENGTH = 8
_CUT_ROOM = _DIGEST_LENGTH + 1

# The shared database's name leaves room for an isolated test's name to
# follow it: at least `_` and a digest.
_SHARED_NAME_LIMIT = MAX_NAME_LENGTH - _CUT_ROOM

# The room kept for a run token is the longest one's, so that where a
# database's name is cut doesn't depend on the run. Every run of a checkout
# then starts its names the same way, which is how one finds what another
# left.
_LONGEST_RUN_TOKEN = len("r4194304x0000")


def _log(msg: str) -> None:
    sys.stderr.write(msg + os.linesep)


def _cut_to(name: str, *, limit: int) -> str:
    """`name` if it fits in `limit`, or its head and a digest of all of it."""
    if len(name) <= limit:
        return name
    digest = names_digest(name, length=_DIGEST_LENGTH)
    return f"{name[: limit - _CUT_ROOM]}_{digest}"


def legacy_database_name(base_name: str) -> str:
    """`test_<database>`: what every run of a checkout starts its names with,
    and the whole name a run used before runs had names of their own."""
    room_for_base = (
        _SHARED_NAME_LIMIT - len(TEST_DATABASE_PREFIX) - _LONGEST_RUN_TOKEN - 1
    )
    return TEST_DATABASE_PREFIX + _cut_to(base_name, limit=room_for_base)


def shared_database_name(base_name: str, *, run_token: str) -> str:
    """`test_<database>_<run token>`, with the database's name cut if it has to be."""
    return f"{legacy_database_name(base_name)}_{run_token}"


def isolated_database_name(shared_name: str, *, test_name: str) -> str:
    """The shared database's name, then the test's without its `test_`:
    there is little room, and every test's name starts that way."""
    test = re.sub(r"[^0-9A-Za-z_]+", "_", test_name).removeprefix("test_")
    return _cut_to(f"{shared_name}_{test}", limit=MAX_NAME_LENGTH)


def _lock_key(shared_name: str) -> int:
    """The advisory lock a run holds, from the name of its shared database."""
    digest = hashlib.sha256(f"plain.postgres.test:{shared_name}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _names_a_run_could_have(database_name: str) -> list[str]:
    """
    Every shared-database name `database_name` could belong to.

    A name is read from its start up to each place a run token ends. Usually
    that is one place. A checkout whose own name holds something shaped
    like a run token gives two, and the database is its run's only if
    neither is held.
    """
    return [
        database_name[: match.end()] for match in _RUN_TOKEN.finditer(database_name)
    ]


class RunDatabases:
    """
    What a run holds for as long as it lives: a connection to the
    maintenance database, and on it the lock that says its databases are
    in use.
    """

    def __init__(self, *, runtime_url: str, management_url: str) -> None:
        if not runtime_url:
            raise ValueError(
                "POSTGRES_URL must be set before creating a test database."
            )
        self.runtime_url = runtime_url
        self.management_url = management_url
        self.config = parse_database_url(runtime_url)

        self.base_name = self.config.get("DATABASE") or ""
        if not self.base_name:
            raise ValueError("POSTGRES_URL must include a database name")

        self.shared_name = ""
        self._maintenance: psycopg.Connection | None = None

    def claim(self) -> None:
        """Take a name for this run, and remove what dead runs left here."""
        maintenance_config: DatabaseConfig = {**self.config, "DATABASE": "postgres"}
        self._maintenance = psycopg.connect(
            **build_connection_params(maintenance_config), autocommit=True
        )

        run_token = f"r{os.getpid()}"
        while True:
            shared_name = shared_database_name(self.base_name, run_token=run_token)
            if self._try_lock(shared_name):
                break
            run_token = f"r{os.getpid()}x{secrets.token_hex(2)}"
        self.shared_name = shared_name

        self._remove_what_dead_runs_left()

    def release(self) -> None:
        """Give the name up. Closing the connection releases the lock."""
        if self._maintenance is not None:
            self._maintenance.close()
            self._maintenance = None

    def isolated_name(self, test_name: str) -> str:
        return isolated_database_name(self.shared_name, test_name=test_name)

    def _try_lock(self, shared_name: str) -> bool:
        assert self._maintenance is not None
        row = self._maintenance.execute(
            "SELECT pg_try_advisory_lock(%s)", [_lock_key(shared_name)]
        ).fetchone()
        assert row is not None
        return row[0]

    def _unlock(self, shared_name: str) -> None:
        assert self._maintenance is not None
        self._maintenance.execute(
            "SELECT pg_advisory_unlock(%s)", [_lock_key(shared_name)]
        )

    def _remove_what_dead_runs_left(self) -> None:
        """
        Drop the test databases of this checkout whose run is no longer
        alive. A database whose run holds its lock is left alone.
        """
        assert self._maintenance is not None
        legacy_name = legacy_database_name(self.base_name)
        rows = self._maintenance.execute(
            "SELECT datname FROM pg_database WHERE starts_with(datname, %s)",
            [legacy_name],
        ).fetchall()

        for (name,) in rows:
            if name.startswith(self.shared_name):
                continue  # this run's own
            if name == legacy_name:
                # `test_<database>`, the name before runs had their own. A
                # run that old holds no lock, so go by whether anything is
                # connected to it.
                if connection_count(self.config, name=name) == 0:
                    drop_database(self.config, name=name)
                continue
            self._remove_if_its_run_is_dead(name)

    def _remove_if_its_run_is_dead(self, database_name: str) -> bool:
        """Drop `database_name` unless a live run holds it. Says whether it did."""
        run_names = _names_a_run_could_have(database_name)
        if not run_names:
            return False  # not named the way a run names its databases

        held = []
        try:
            for run_name in run_names:
                if not self._try_lock(run_name):
                    return False  # a live run's
                held.append(run_name)
            # Holding the lock while dropping: a new run can't take the
            # name and create this database in the middle of it.
            drop_database(self.config, name=database_name, force=True)
            return True
        finally:
            for run_name in held:
                self._unlock(run_name)


def database_is_a_live_runs(config: DatabaseConfig, *, name: str) -> bool:
    """
    Whether a run that is alive holds `name`. For `plain db clean` and the
    like: a test database that is nobody's can be dropped, and one that a
    run holds can't, even in the moment before the run connects to it.
    """
    run_names = _names_a_run_could_have(name)
    if not run_names:
        return False

    maintenance_config: DatabaseConfig = {**config, "DATABASE": "postgres"}
    with psycopg.connect(
        **build_connection_params(maintenance_config), autocommit=True
    ) as maintenance:
        for run_name in run_names:
            key = _lock_key(run_name)
            row = maintenance.execute(
                "SELECT pg_try_advisory_lock(%s)", [key]
            ).fetchone()
            assert row is not None
            if not row[0]:
                return True
            maintenance.execute("SELECT pg_advisory_unlock(%s)", [key])
    return False


def _create_test_database(config: DatabaseConfig, *, name: str, verbosity: int) -> None:
    """Create the test database, replacing one of the same name.

    A run's names are its own, so a database already here under one of
    them is what an earlier run with the same process id left.
    """
    try:
        create_database(config, name=name)
        return
    except errors.DuplicateDatabase:
        pass
    except Exception as e:
        _log(f"Got an error creating the test database: {e}")
        sys.exit(2)

    try:
        if verbosity >= 1:
            _log(f"Destroying old test database '{name}'...")
        drop_database(config, name=name, force=True)
        create_database(config, name=name)
    except Exception as e:
        _log(f"Got an error recreating the test database: {e}")
        sys.exit(2)


@contextmanager
def use_test_database(
    *, name: str, runtime_url: str, management_url: str = "", verbosity: int = 1
) -> Generator[str]:
    """Create the database `name`, make it the one in use, drop it on exit.

    Inside the block `get_connection()` returns a connection to it in this
    context, and the pool hands out connections to it in every other (see
    the module docstring). Migrations and convergence run through their
    Python APIs (`MigrationExecutor`, `plan_convergence`), not the CLI
    commands.

    `runtime_url` and `management_url` are the URLs as configured, before
    any test database was put in their place.

    Yields the test database's name.
    """
    from plain.postgres.convergence import execute_plan, plan_convergence

    if verbosity >= 1:
        _log(f"Creating test database '{name}'...")

    test_url = replace_database_name(runtime_url, name)
    test_config = parse_database_url(test_url)
    test_conn = DatabaseConnection(DirectSource(test_config))

    # Create the test database on the server via a direct `postgres`-DB
    # connection — test_conn itself can't connect to a DB that doesn't
    # exist yet, so we open a sibling connection against `postgres`.
    _create_test_database(test_config, name=name, verbosity=verbosity)

    url_before = settings.POSTGRES_URL
    management_url_before = settings.POSTGRES_MANAGEMENT_URL

    conn_token = _db_conn.set(test_conn)
    # The pool was built on the URL as it was. Closed, it is rebuilt on
    # the setting as it is now by whoever next asks it for a connection.
    runtime_pool_source.close()
    settings.POSTGRES_URL = test_url
    if management_url and management_url.lower() != "none":
        settings.POSTGRES_MANAGEMENT_URL = replace_database_name(management_url, name)
    try:
        executor = MigrationExecutor(test_conn)
        targets = list(executor.loader.graph.leaf_nodes())
        executor.migrate(targets)

        plan = plan_convergence()
        result = execute_plan(plan.executable())
        if not result.ok:
            failed = [r for r in result.results if not r.ok]
            raise RuntimeError(
                f"Convergence failed during test DB setup: {failed[0].item.describe()} — {failed[0].error}"
            )
        # A fresh DB from migrations shouldn't have undeclared objects or
        # changed definitions — safety net so test setup follows sync policy.
        if plan.blocked:
            problem = plan.blocked[0]
            raise RuntimeError(
                f"Convergence blocked during test DB setup: {problem.describe()}"
            )

        test_conn.ensure_connection()

        yield name
    finally:
        _db_conn.reset(conn_token)

        try:
            test_conn.close()
        except Exception:
            pass

        # The pool's connections are to this database. Closed before the
        # settings go back, so nothing is handed one in between.
        runtime_pool_source.close()
        settings.POSTGRES_URL = url_before
        settings.POSTGRES_MANAGEMENT_URL = management_url_before

        if verbosity >= 1:
            _log(f"Destroying test database '{name}'...")
        try:
            # Forced: a thread the code under test started may still hold a
            # connection, and the run that used this database is done with it.
            drop_database(test_config, name=name, force=True)
        except Exception as e:
            _log(f"Got an error destroying the test database: {e}")
