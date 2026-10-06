"""
The databases a test run uses, and how the run is pointed at them.

A run has databases of its own, named for the checkout's database and for
the run:

    test_<database>_r<pid>                   the rolled-back tests share it
    test_<database>_r<pid>_<test name>       one `@isolated_db` test's

So any number of runs in one checkout, at the same moment, each create,
use and drop their own. A run that ends drops its databases. One that was
killed leaves them, and the next run of that database removes them.

**The template.** A run's databases are clones of one more, which stays:

    test_<database>_t<schema>                migrated and converged once

It is built by the first run that needs it, from nothing (create, migrate,
converge), and every run after clones it with `CREATE DATABASE ... TEMPLATE`,
which copies the files and takes a moment whatever the schema. It is named
by a digest of what it was built from (`schema.py`), so a changed migration
or model is a new template, and the old one is removed by the next run's
sweep. One is kept per checkout's database.

**What a run may drop.** Its own databases, which it made. And what a dead
run left, which it didn't, so that is decided narrowly: only a database
that carries a run's record, for this configured database exactly, whose
run is proved dead; or a template's record, for this database exactly, that
is of no use now. `leftovers.py` has the rules. A database is never looked
for by the start of its name.

**Which runs are alive.** For as long as it lives, a run holds a session
advisory lock on the `postgres` maintenance database, keyed by the name of
its shared database. Postgres releases the lock when the run's connection
goes, however the run ended. A run building or cloning the template holds
the template's lock the same way, for as long as that takes.

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
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace

import psycopg
from plain.postgres.connection import DatabaseConnection
from plain.postgres.database_url import (
    DatabaseConfig,
    parse_database_url,
    replace_database_name,
)
from plain.postgres.databases import (
    create_database,
    database_exists,
    drop_database,
    get_database_comment,
    set_database_comment,
    terminate_connections,
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
    TEMPLATE_BUILDING,
    TEMPLATE_READY,
    RunRecord,
    TemplateRecord,
    read_run_record,
    read_template_record,
    remove_what_dead_runs_left,
    run_lock_key,
)
from .schema import SchemaDigest, read_server_version

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
# digits follow. A template's token, `t` and eight hex digits of its
# schema's digest, fits in the same room.
_LONGEST_RUN_TOKEN = len("r4194304x0000")
_SCHEMA_IN_NAME = 8


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


def template_database_name(base_name: str, *, schema: str) -> str:
    """`test_<database>_t<schema>`: the template every run of the database
    clones, named by the first eight hex digits of its schema's digest."""
    return shared_database_name(base_name, run_token=f"t{schema[:_SCHEMA_IN_NAME]}")


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
        self.schema: SchemaDigest | None = None
        self.template_name = ""
        # What was done about the template, for the run's report: ("built
        # template (49 migrations)", seconds), ("cloned template", seconds).
        self.setup_parts: list[tuple[str, float]] = []
        self._maintenance: psycopg.Connection | None = None

    def server_version(self) -> str:
        """The version of the server the run's databases are on, which is
        part of what they are built from (`describe_schema`)."""
        return read_server_version(self._maintenance_connection())

    def claim(self, *, schema: SchemaDigest) -> None:
        """Take a name for this run, and remove what dead runs left here.

        `schema` is the digest of what the run's databases are built from
        (`describe_schema()`), which names the template they are cloned
        from.
        """
        self._maintenance = self._maintenance_connection()
        self.schema = schema
        self.template_name = template_database_name(self.base_name, schema=schema.hash)

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
            current_schema=schema.hash,
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

    def record_for_the_template(self) -> TemplateRecord:
        """What this run writes into the template it builds."""
        assert self.schema is not None
        return TemplateRecord(
            database=self.base_name,
            schema=self.schema.hash,
            state=TEMPLATE_BUILDING,
            directory=os.getcwd(),
            host=socket.gethostname(),
            pid=os.getpid(),
        )

    def create_from_template(self, *, name: str) -> None:
        """Create the database `name` as a clone of the template, building
        the template first if no run has.

        The template's lock is held throughout, so two runs never build it
        at once, and nothing drops it while a run is cloning it. A run that
        finds the lock held waits: the run holding it is building the
        template, or cloning it, which takes a moment.
        """
        assert self._maintenance is not None
        key = run_lock_key(self.template_name)
        self._maintenance.execute("SELECT pg_advisory_lock(%s)", [key])
        try:
            self._ensure_template()
            started = time.perf_counter()
            _create_test_database(
                self.config,
                name=name,
                made_by=self.record_for_a_database(),
                template=self.template_name,
            )
            self.setup_parts.append(("cloned template", time.perf_counter() - started))
        finally:
            self._maintenance.execute("SELECT pg_advisory_unlock(%s)", [key])

    def _ensure_template(self) -> None:
        """Build the template if it isn't there, ready, for this schema.

        Called with the template's lock held. A database of the template's
        name that carries a template record for this configured database
        is a template of this run's own kind: one a run left half built,
        or one for a schema whose digest starts the same way. It is dropped
        and built again. Any other database of the name is somebody's, and
        is left: the run stops.
        """
        assert self.schema is not None
        name = self.template_name
        found = read_template_record(get_database_comment(self.config, name=name))
        if (
            found is not None
            and found.database == self.base_name
            and found.schema == self.schema.hash
            and found.state == TEMPLATE_READY
        ):
            return

        if database_exists(self.config, name=name):
            if found is None or found.database != self.base_name:
                raise RuntimeError(
                    f"A database named {name!r} is already there, and no test run"
                    " of this database built it, so it is left as it is. This run"
                    f" needs the name. If the database is debris: plain db drop {name}"
                )
            # Not forced: nothing should be connected to a template that no
            # run holds the lock on, and if something is, it is in use.
            drop_database(self.config, name=name, force=False)

        started = time.perf_counter()
        record = self.record_for_the_template()
        create_database(self.config, name=name)
        set_database_comment(self.config, name=name, comment=record.as_comment())
        with _pointed_at(
            name, runtime_url=self.runtime_url, management_url=self.management_url
        ) as connection:
            _migrate_and_converge(connection)
        set_database_comment(
            self.config,
            name=name,
            comment=replace(record, state=TEMPLATE_READY).as_comment(),
        )
        self.setup_parts.append(
            (
                f"built template ({_migrations(self.schema.migrations)})",
                time.perf_counter() - started,
            )
        )

    def _maintenance_connection(self) -> psycopg.Connection:
        """The run's connection to the maintenance database, opened the
        first time it is asked for and held until `release()`."""
        if self._maintenance is None:
            maintenance_config: DatabaseConfig = {**self.config, "DATABASE": "postgres"}
            self._maintenance = psycopg.connect(
                **build_connection_params(maintenance_config), autocommit=True
            )
        return self._maintenance

    def _try_lock(self, shared_name: str) -> bool:
        assert self._maintenance is not None
        row = self._maintenance.execute(
            "SELECT pg_try_advisory_lock(%s)", [run_lock_key(shared_name)]
        ).fetchone()
        assert row is not None
        return row[0]


def _migrations(count: int) -> str:
    return "1 migration" if count == 1 else f"{count} migrations"


def _create_test_database(
    config: DatabaseConfig, *, name: str, made_by: RunRecord, template: str
) -> None:
    """Create the database `name` as a clone of `template`, and write into
    it that this run made it.

    A database already there under the name is replaced only if its record
    says a run of this one's name made it. This run holds that name's lock,
    so that run is this one, or an earlier one with the same process id
    that is gone. Any other database of the name is somebody's, and is
    left: the run stops.
    """
    try:
        _clone(config, name=name, template=template)
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
        _clone(config, name=name, template=template)

    set_database_comment(config, name=name, comment=made_by.as_comment())


def _clone(config: DatabaseConfig, *, name: str, template: str) -> None:
    """`CREATE DATABASE name TEMPLATE template`.

    Postgres refuses while anything is connected to the template. The run
    holds the template's lock, so no other run is building or cloning it,
    and a connection to it is one this process left open (the pool is
    closed after the build, but a thread of the code under test may have
    taken one): it is ended, and the clone tried once more.
    """
    try:
        create_database(config, name=name, template=template)
    except errors.ObjectInUse:
        terminate_connections(config, name=template)
        create_database(config, name=name, template=template)


@contextmanager
def _pointed_at(
    name: str, *, runtime_url: str, management_url: str
) -> Generator[DatabaseConnection]:
    """Make the database `name` the one in use, for the block.

    Inside it `get_connection()` returns a connection to it in this
    context, and the pool hands out connections to it in every other (see
    the module docstring). On exit the connection and the pool are closed,
    so nothing of this process is connected to it, and the settings are as
    they were.

    `runtime_url` and `management_url` are the URLs as configured, before
    any test database was put in their place.
    """
    url = replace_database_name(runtime_url, name)
    connection = DatabaseConnection(DirectSource(parse_database_url(url)))

    url_before = settings.POSTGRES_URL
    management_url_before = settings.POSTGRES_MANAGEMENT_URL

    conn_token = _db_conn.set(connection)
    # The pool was built on the URL as it was. Closed, it is rebuilt on
    # the setting as it is now by whoever next asks it for a connection.
    runtime_pool_source.close()
    settings.POSTGRES_URL = url
    if management_url and management_url.lower() != "none":
        settings.POSTGRES_MANAGEMENT_URL = replace_database_name(management_url, name)
    try:
        yield connection
    finally:
        _db_conn.reset(conn_token)

        try:
            connection.close()
        except Exception:
            pass

        # The pool's connections are to this database. Closed before the
        # settings go back, so nothing is handed one in between.
        runtime_pool_source.close()
        settings.POSTGRES_URL = url_before
        settings.POSTGRES_MANAGEMENT_URL = management_url_before


def _migrate_and_converge(connection: DatabaseConnection) -> None:
    """Every migration, then convergence, through their Python APIs
    (`MigrationExecutor`, `plan_convergence`), not the CLI commands."""
    from plain.postgres.convergence import execute_plan, plan_convergence

    executor = MigrationExecutor(connection)
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


@contextmanager
def use_test_database(
    *, run: RunDatabases, name: str, verbosity: int = 1
) -> Generator[str]:
    """Create the database `name` for `run`, make it the one in use, drop
    it on exit.

    It is a clone of the run's template, so it is migrated and converged
    already (`RunDatabases.create_from_template`). Inside the block the
    process is pointed at it (`_pointed_at`).

    Yields the test database's name.
    """
    if verbosity >= 1:
        _log(f"Creating test database '{name}'...")

    run.create_from_template(name=name)
    test_config = parse_database_url(replace_database_name(run.runtime_url, name))

    try:
        with _pointed_at(
            name, runtime_url=run.runtime_url, management_url=run.management_url
        ) as connection:
            connection.ensure_connection()
            yield name
    finally:
        if verbosity >= 1:
            _log(f"Destroying test database '{name}'...")
        try:
            # Forced, and the one place a database is: this run made it a
            # moment ago and is done with it, and a thread the code under
            # test started may still hold a connection.
            drop_database(test_config, name=name, force=True)
        except Exception as e:
            _log(f"Got an error destroying the test database: {e}")
