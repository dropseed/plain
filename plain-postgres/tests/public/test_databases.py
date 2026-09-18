"""`plain.postgres.databases` against a real server.

These run wherever a Postgres is configured, CI included, because they build
their own throwaway databases on whatever cluster `POSTGRES_URL` points at.
The role needs CREATEDB — which is the point of the module, and true of every
development and CI Postgres.

Every scratch database is named for this run (see `PREFIX`), so two suites
sharing a cluster can't drop each other's.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Generator
from contextlib import contextmanager

import psycopg
from plain.postgres.database_url import DatabaseConfig, parse_database_url
from plain.postgres.databases import (
    connection_count,
    create_database,
    database_exists,
    drop_database,
    get_database_comment,
    list_databases,
    maintenance_cursor,
    set_database_comment,
    terminate_connections,
)
from plain.runtime import settings
from plain.test import raises

# Scratch databases are named per run, not per suite. A fixed prefix means two
# runs against one cluster — a CI matrix, parallel worktrees — hand out the
# same names, and one run's `drop_database(force=True)` destroys the other's
# database mid-test. The token is generated once per process, and the prefix
# still identifies anything a crashed run leaves behind.
PREFIX = f"plain_databases_test_{secrets.token_hex(4)}_"


def database_config() -> DatabaseConfig:
    return parse_database_url(str(settings.POSTGRES_URL))


@contextmanager
def scratch_names(config: DatabaseConfig) -> Generator[Callable[[str], str]]:
    """Yield a name factory; drop everything it handed out afterwards."""
    created: list[str] = []

    def make(suffix: str) -> str:
        name = f"{PREFIX}{suffix}"
        drop_database(config, name=name, force=True)
        created.append(name)
        return name

    try:
        yield make
    finally:
        for name in created:
            drop_database(config, name=name, force=True)


def test_create_and_drop():
    config = database_config()
    with scratch_names(config) as scratch:
        name = scratch("basic")
        assert not database_exists(config, name=name)

        create_database(config, name=name)
        assert database_exists(config, name=name)

        drop_database(config, name=name)
        assert not database_exists(config, name=name)


def test_create_duplicate_raises():
    config = database_config()
    with scratch_names(config) as scratch:
        name = scratch("dupe")
        create_database(config, name=name)

        with raises(psycopg.errors.DuplicateDatabase):
            create_database(config, name=name)


def test_drop_is_idempotent():
    """`DROP DATABASE IF EXISTS`, so cleanup paths don't have to check first."""
    config = database_config()
    with scratch_names(config) as scratch:
        drop_database(config, name=scratch("never_created"))


def test_template_copies_data():
    """The primitive dev forking is built on: a copy that carries its rows."""
    config = database_config()
    with scratch_names(config) as scratch:
        source = scratch("template_source")
        clone = scratch("template_clone")

        create_database(config, name=source)
        source_url = _url_for(config, source)
        with psycopg.connect(source_url, autocommit=True) as conn:
            conn.execute("CREATE TABLE widget (id int)")
            conn.execute("INSERT INTO widget VALUES (1), (2), (3)")

        create_database(config, name=clone, template=source)

        with psycopg.connect(_url_for(config, clone)) as conn:
            row = conn.execute("SELECT count(*) FROM widget").fetchone()
            assert row is not None
            assert row[0] == 3


def test_comment_round_trips_raw_text():
    config = database_config()
    with scratch_names(config) as scratch:
        name = scratch("comment")
        create_database(config, name=name)

        assert get_database_comment(config, name=name) is None

        set_database_comment(config, name=name, comment='{"checkout": "/tmp/x"}')
        assert get_database_comment(config, name=name) == '{"checkout": "/tmp/x"}'


def test_comment_survives_quotes():
    """Comments are literal-escaped, so apostrophes can't break the statement."""
    config = database_config()
    with scratch_names(config) as scratch:
        name = scratch("quoting")
        create_database(config, name=name)

        set_database_comment(config, name=name, comment='it\'s "quoted"')
        assert get_database_comment(config, name=name) == 'it\'s "quoted"'


def test_list_databases():
    config = database_config()
    with scratch_names(config) as scratch:
        first = scratch("list_a")
        second = scratch("list_b")
        create_database(config, name=first)
        create_database(config, name=second)
        set_database_comment(config, name=first, comment="hello")

        listed = list_databases(config)
        by_name = {info.name: info for info in listed}

        assert first in by_name
        assert second in by_name
        assert by_name[first].comment == "hello"
        assert by_name[second].comment is None
        assert by_name[first].size_bytes > 0
        # Cluster furniture is never listed.
        assert "postgres" not in by_name
        assert "template1" not in by_name


def test_connection_count_and_terminate():
    config = database_config()
    with scratch_names(config) as scratch:
        name = scratch("busy")
        create_database(config, name=name)
        url = _url_for(config, name)

        assert connection_count(config, name=name) == 0

        held = psycopg.connect(url)
        try:
            assert connection_count(config, name=name) == 1

            terminate_connections(config, name=name)
            assert connection_count(config, name=name) == 0
        finally:
            held.close()


def test_template_requires_idle_source():
    """Why fork picks its mechanism: TEMPLATE is refused while anyone is connected."""
    config = database_config()
    with scratch_names(config) as scratch:
        source = scratch("idle_source")
        clone = scratch("idle_clone")
        create_database(config, name=source)

        held = psycopg.connect(_url_for(config, source))
        try:
            with raises(psycopg.errors.ObjectInUse):
                create_database(config, name=clone, template=source)
        finally:
            held.close()

        # Once it's idle the same call succeeds.
        create_database(config, name=clone, template=source)
        assert database_exists(config, name=clone)


def test_maintenance_cursor_targets_the_postgres_database():
    with maintenance_cursor(database_config()) as cursor:
        row = cursor.execute("SELECT current_database()").fetchone()
        assert row is not None
        assert row[0] == "postgres"


def _url_for(config: DatabaseConfig, db_name: str) -> str:
    user = config.get("USER") or ""
    password = config.get("PASSWORD") or ""
    host = config.get("HOST") or "127.0.0.1"
    port = config.get("PORT") or 5432
    return f"postgres://{user}:{password}@{host}:{port}/{db_name}"
