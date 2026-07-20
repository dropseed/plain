"""Pins the connection-failure taxonomy in `readiness.py`.

psycopg3 exposes no sqlstate on connection-time failures (verified against
psycopg 3.2), so classification falls back to message matching there — these
tests pin both paths and the safe default (unknown → retryable).
"""

from __future__ import annotations

import psycopg
import pytest

from plain.exceptions import ImproperlyConfigured
from plain.postgres import readiness
from plain.postgres.connection import DatabaseConnection
from plain.postgres.database_url import DatabaseConfig
from plain.postgres.db import get_connection
from plain.postgres.readiness import (
    ReadinessStatus,
    _classify_connection_failure,
    check_database_ready,
)
from plain.postgres.sources import DirectSource


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        # Connection-time failures: sqlstate is None, match on the message.
        (
            'connection failed: FATAL:  password authentication failed for user "app"',
            ReadinessStatus.CONFIG_ERROR,
        ),
        (
            'connection failed: FATAL:  no pg_hba.conf entry for host "10.0.0.1"',
            ReadinessStatus.CONFIG_ERROR,
        ),
        (
            'connection failed: FATAL:  database "appdb" does not exist',
            ReadinessStatus.CONFIG_ERROR,
        ),
        (
            'connection failed: FATAL:  role "app" does not exist',
            ReadinessStatus.CONFIG_ERROR,
        ),
        # libpq rejects bad values for recognized options client-side.
        (
            'connection is bad: invalid sslmode value: "bogus"',
            ReadinessStatus.CONFIG_ERROR,
        ),
        (
            'invalid integer value "abc" for connection option "connect_timeout"',
            ReadinessStatus.CONFIG_ERROR,
        ),
        # A DB restart mid-deploy must never read as permanent.
        (
            "connection failed: FATAL:  the database system is starting up",
            ReadinessStatus.UNREACHABLE,
        ),
        (
            "connection failed: FATAL:  sorry, too many clients already",
            ReadinessStatus.UNREACHABLE,
        ),
        (
            'connection to server at "127.0.0.1", port 5432 failed: Connection refused',
            ReadinessStatus.UNREACHABLE,
        ),
        (
            "[Errno 8] nodename nor servname provided, or not known",
            ReadinessStatus.UNREACHABLE,
        ),
        ("connection timeout expired", ReadinessStatus.UNREACHABLE),
    ],
)
def test_connect_time_message_classification(message, expected):
    assert _classify_connection_failure(psycopg.OperationalError(message)) is expected


def test_query_time_sqlstate_classification():
    # Query-time failures carry a sqlstate on the error class.
    assert (
        _classify_connection_failure(psycopg.errors.InvalidPassword("denied"))
        is ReadinessStatus.CONFIG_ERROR
    )
    # Server shutting down mid-check — retryable.
    assert (
        _classify_connection_failure(psycopg.errors.AdminShutdown("terminating"))
        is ReadinessStatus.UNREACHABLE
    )


def test_improperly_configured_url_is_config_error(monkeypatch):
    def raise_improperly_configured():
        raise ImproperlyConfigured("POSTGRES_URL is not set.")

    monkeypatch.setattr(readiness, "_parse_runtime_url", raise_improperly_configured)

    result = check_database_ready()

    assert result.status is ReadinessStatus.CONFIG_ERROR
    assert "POSTGRES_URL" in (result.connection_error or "")


def test_invalid_url_is_config_error(monkeypatch):
    # parse_database_url raises ValueError for e.g. an unsupported scheme
    # (mysql://...) — permanent, so it must classify as config error rather
    # than crash with a traceback (whose exit 1 would read as retryable).
    def raise_value_error():
        raise ValueError("No support for 'mysql'.")

    monkeypatch.setattr(readiness, "_parse_runtime_url", raise_value_error)

    result = check_database_ready()

    assert result.status is ReadinessStatus.CONFIG_ERROR
    assert "mysql" in (result.connection_error or "")


def test_insufficient_privilege_is_config_error(db, monkeypatch):
    # A runtime/management role split that misses the SELECT grant on
    # plainmigrations raises InsufficientPrivilege (a ProgrammingError, not
    # OperationalError) from the checks — a grant a human must add, so it
    # classifies instead of crashing with a traceback.
    def raise_insufficient_privilege(conn):
        raise psycopg.errors.InsufficientPrivilege(
            "permission denied for table plainmigrations"
        )

    monkeypatch.setattr(readiness, "_pending_migrations", raise_insufficient_privilege)

    result = check_database_ready(conn=get_connection())

    assert result.status is ReadinessStatus.CONFIG_ERROR
    assert "permission denied" in (result.connection_error or "")


def test_invalid_connection_option_is_config_error(db):
    # psycopg rejects an unknown connection option (a typo'd URL query
    # param) with ProgrammingError at connect time — config-shaped.
    config: DatabaseConfig = {
        **get_connection().settings_dict,
        "OPTIONS": {"not_a_real_option": "1"},
    }
    conn = DatabaseConnection(DirectSource(config))

    result = check_database_ready(conn=conn)

    assert result.status is ReadinessStatus.CONFIG_ERROR
    assert "not_a_real_option" in (result.connection_error or "")
