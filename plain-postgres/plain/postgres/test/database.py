"""
The databases a test run uses, and how the run is pointed at them.

A run has databases of its own, named for the checkout's database and for
the run:

    test_<database>_r<pid>                   the rolled-back tests share it
    test_<database>_r<pid>_<test name>       one `@isolated_db` test's

So any number of runs in one checkout, at the same moment, each create,
use and drop their own. A run that ends drops its databases. One that was
killed leaves them, and the next run of that database removes them.

**What a run may drop.** Its own databases, which it made. And what a dead
run left, which it didn't, so that is decided narrowly: only a database
that carries a run's record, for this configured database exactly, whose
run is proved dead. `leftovers.py` has the rule. A database is never
looked for by the start of its name.

**Which runs are alive.** For as long as it lives, a run holds a session
advisory lock on the `postgres` maintenance database, keyed by the name of
its shared database. Postgres releases the lock when the run's connection
goes, however the run ended.

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

import os
import re
import secrets
import socket
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
    create_database,
    drop_database,
    get_database_comment,
    set_database_comment,
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

from .leftovers import (
    RunRecord,
    read_run_record,
    remove_what_dead_runs_left,
    run_lock_key,
)

TEST_DATABASE_PREFIX = "test_"

# The digest that ends a name that had to be cut to fit, and the `_` before it.
_DIGEST_LENGTH = 8
_CUT_ROOM = _DIGEST_LENGTH + 1

# The shared database's name leaves room for an isolated test's name to
# follow it: at least `_` and a digest.
_SHARED_NAME_LIMIT = MAX_NAME_LENGTH - _CUT_ROOM

# The room kept for a run token is the longest one's, so that where a
# database's name is cut doesn't depend on the run, and every run of a
# checkout starts its names the same way. A run token is `r` and the
# process id. When another live run already holds that name (the same
# process id on another machine, on one server), `x` and four random hex
# digits follow.
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

        remove_what_dead_runs_left(
            self._maintenance,
            self.config,
            tested_database=self.base_name,
            held_run=self.shared_name,
            say=_log,
        )

    def release(self) -> None:
        """Give the name up. Closing the connection releases the lock."""
        if self._maintenance is not None:
            self._maintenance.close()
            self._maintenance = None

    def isolated_name(self, test_name: str) -> str:
        return isolated_database_name(self.shared_name, test_name=test_name)

    def record_for_a_database(self) -> RunRecord:
        """What this run writes into a database it creates: that a test run
        made it, for which configured database, and which run."""
        return RunRecord(
            database=self.base_name,
            run=self.shared_name,
            token=secrets.token_hex(8),
            directory=os.getcwd(),
            host=socket.gethostname(),
            pid=os.getpid(),
        )

    def _try_lock(self, shared_name: str) -> bool:
        assert self._maintenance is not None
        row = self._maintenance.execute(
            "SELECT pg_try_advisory_lock(%s)", [run_lock_key(shared_name)]
        ).fetchone()
        assert row is not None
        return row[0]


def _create_test_database(
    config: DatabaseConfig, *, name: str, made_by: RunRecord
) -> None:
    """Create the database `name`, and write into it that this run made it.

    A database already there under the name is replaced only if its record
    says a run of this one's name made it. This run holds that name's lock,
    so that run is this one, or an earlier one with the same process id
    that is gone. Any other database of the name is somebody's, and is
    left: the run stops.
    """
    try:
        create_database(config, name=name)
    except errors.DuplicateDatabase:
        found = read_run_record(get_database_comment(config, name=name))
        if (
            found is None
            or found.database != made_by.database
            or found.run != made_by.run
        ):
            raise RuntimeError(
                f"A database named {name!r} is already there, and no test run"
                " of this name made it, so it is left as it is. This run"
                f" needs the name. If the database is debris: plain db drop {name}"
            ) from None
        # Forced: it is this run's name, and this run holds the name's lock.
        drop_database(config, name=name, force=True)
        create_database(config, name=name)

    set_database_comment(config, name=name, comment=made_by.as_comment())


@contextmanager
def use_test_database(
    *,
    name: str,
    made_by: RunRecord,
    runtime_url: str,
    management_url: str = "",
    verbosity: int = 1,
) -> Generator[str]:
    """Create the database `name`, make it the one in use, drop it on exit.

    `made_by` is the record written into it (`RunDatabases.record_for_a_database`).

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
    _create_test_database(test_config, name=name, made_by=made_by)

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
            # Forced, and the one place a database is: this run made it a
            # moment ago and is done with it, and a thread the code under
            # test started may still hold a connection.
            drop_database(test_config, name=name, force=True)
        except Exception as e:
            _log(f"Got an error destroying the test database: {e}")
