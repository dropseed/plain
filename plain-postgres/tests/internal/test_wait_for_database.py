"""The connectivity wait that fronts the schema commands.

`cli_wait_for_database()` retries while the database is unreachable and
fails immediately on configuration errors, using the same classification
as `plain postgres ready`.
"""

from __future__ import annotations

import click
import pytest

from plain.postgres.cli.decorators import cli_wait_for_database
from plain.postgres.connection import DatabaseConnection
from plain.postgres.database_url import DatabaseConfig
from plain.postgres.db import _db_conn, get_connection
from plain.postgres.sources import DirectSource


def test_returns_immediately_when_already_connected(db):
    # The test connection is open (inside the db fixture's transaction) —
    # the wait must be a no-op, not a fresh probe.
    cli_wait_for_database()


def _use_connection(config: DatabaseConfig):
    conn = DatabaseConnection(DirectSource(config))
    return _db_conn.set(conn)


def test_config_error_fails_immediately(db):
    config: DatabaseConfig = {
        **get_connection().settings_dict,
        "OPTIONS": {"not_a_real_option": "1"},
    }
    token = _use_connection(config)
    try:
        with pytest.raises(click.ClickException, match="not_a_real_option"):
            cli_wait_for_database()
    finally:
        _db_conn.reset(token)


def test_unreachable_retries_until_timeout(db, settings):
    settings.POSTGRES_WAIT_TIMEOUT = 0.0  # one attempt, then give up
    config: DatabaseConfig = {
        **get_connection().settings_dict,
        "HOST": "127.0.0.1",
        "PORT": 59999,
    }
    token = _use_connection(config)
    try:
        with pytest.raises(click.ClickException, match="not reachable after 1 attempt"):
            cli_wait_for_database()
    finally:
        _db_conn.reset(token)
