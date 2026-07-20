"""The readiness contract consumed by serving entrypoints.

`check_database_ready()` truthfully classifies whether the database can
serve this code, and `plain postgres ready` maps that classification to
exit codes — 0 = ready, 1 = not ready but retryable, 2 = configuration
error a human must fix — with DEBUG downgrading schema gaps to warnings.

All database staging here runs inside the `db` fixture's transaction —
Postgres DDL is transactional, so dropped tables/columns roll back.
"""

from __future__ import annotations

import json

from app.examples.models.defaults import DefaultsExample
from click.testing import CliRunner

from plain.postgres.cli import ready as ready_cli
from plain.postgres.db import get_connection
from plain.postgres.migrations.recorder import MigrationRecorder
from plain.postgres.readiness import (
    ReadinessResult,
    ReadinessStatus,
    check_database_ready,
)

DATA_MIGRATION = "0019_readiness_data_migration"


def test_ready_when_synced(db):
    result = check_database_ready(conn=get_connection())

    assert result.status is ReadinessStatus.READY
    assert result.pending_migrations == []
    assert result.pending_data_migrations == []
    assert result.missing_tables == []
    assert result.missing_columns == []


def test_pending_schema_migration_gates(db):
    recorder = MigrationRecorder(get_connection())
    # A schema-affecting migration (AddField) missing its applied record —
    # what a pod sees when its image is ahead of the database.
    recorder.record_unapplied("examples", "0017_random_string_token")

    result = check_database_ready(conn=get_connection())

    assert result.status is ReadinessStatus.PENDING_MIGRATIONS
    assert "examples.0017_random_string_token" in result.pending_migrations


def test_pending_data_migration_warns_not_gates(db):
    recorder = MigrationRecorder(get_connection())
    # An all-RunPython migration pending — a long backfill mid-flight.
    recorder.record_unapplied("examples", DATA_MIGRATION)

    result = check_database_ready(conn=get_connection())

    assert result.status is ReadinessStatus.READY
    assert result.pending_migrations == []
    assert f"examples.{DATA_MIGRATION}" in result.pending_data_migrations


def test_missing_column_not_satisfied(db):
    conn = get_connection()
    table = DefaultsExample.model_options.db_table
    with conn.cursor() as cursor:
        cursor.execute(f'ALTER TABLE "{table}" DROP COLUMN status')

    result = check_database_ready(conn=conn)

    assert result.status is ReadinessStatus.SCHEMA_NOT_SATISFIED
    assert f"{table}.status" in result.missing_columns
    assert result.pending_migrations == []


def test_missing_table_not_satisfied(db):
    conn = get_connection()
    table = DefaultsExample.model_options.db_table
    with conn.cursor() as cursor:
        cursor.execute(f'DROP TABLE "{table}" CASCADE')

    result = check_database_ready(conn=conn)

    assert result.status is ReadinessStatus.SCHEMA_NOT_SATISFIED
    assert table in result.missing_tables


def test_fresh_database_is_pending_migrations(db):
    conn = get_connection()
    # No plainmigrations table at all — a brand-new database a scheduled
    # migrate hasn't touched yet. Classified as pending (retryable), not
    # as an error.
    with conn.cursor() as cursor:
        cursor.execute("DROP TABLE plainmigrations")

    result = check_database_ready(conn=conn)

    assert result.status is ReadinessStatus.PENDING_MIGRATIONS
    assert result.pending_migrations


def _invoke_ready_with_status(monkeypatch, status: ReadinessStatus):
    monkeypatch.setattr(
        ready_cli,
        "check_database_ready",
        lambda: ReadinessResult(status=status, connection_error="error detail"),
    )
    return CliRunner().invoke(ready_cli.ready, [])


def test_cli_exit_codes(monkeypatch, settings):
    settings.DEBUG = False
    expected = {
        ReadinessStatus.READY: 0,
        ReadinessStatus.PENDING_MIGRATIONS: 1,
        ReadinessStatus.SCHEMA_NOT_SATISFIED: 1,
        ReadinessStatus.UNREACHABLE: 1,
        ReadinessStatus.CONFIG_ERROR: 2,
    }
    for status, exit_code in expected.items():
        result = _invoke_ready_with_status(monkeypatch, status)
        assert result.exit_code == exit_code, (
            f"{status} should exit {exit_code}, got {result.exit_code}\n{result.output}"
        )


def test_cli_exit_codes_debug_warns_past_schema_gaps(monkeypatch, settings):
    settings.DEBUG = True
    # Mid-development, gaps warn instead of gating — but an unreachable
    # database or a config error still fails; nothing serves through those.
    expected = {
        ReadinessStatus.READY: 0,
        ReadinessStatus.PENDING_MIGRATIONS: 0,
        ReadinessStatus.SCHEMA_NOT_SATISFIED: 0,
        ReadinessStatus.UNREACHABLE: 1,
        ReadinessStatus.CONFIG_ERROR: 2,
    }
    for status, exit_code in expected.items():
        result = _invoke_ready_with_status(monkeypatch, status)
        assert result.exit_code == exit_code, (
            f"{status} should exit {exit_code} in DEBUG, got {result.exit_code}\n{result.output}"
        )

    result = _invoke_ready_with_status(monkeypatch, ReadinessStatus.PENDING_MIGRATIONS)
    assert "DEBUG" in result.output


def test_cli_json_includes_exit_code(monkeypatch, settings):
    settings.DEBUG = True
    # In DEBUG the process exits 0 while the classification stays truthful —
    # the JSON payload carries the exit code so machine consumers can
    # reconcile the two.
    monkeypatch.setattr(
        ready_cli,
        "check_database_ready",
        lambda: ReadinessResult(status=ReadinessStatus.PENDING_MIGRATIONS),
    )
    result = CliRunner().invoke(ready_cli.ready, ["--json"])

    payload = json.loads(result.output)
    assert payload["status"] == "pending-migrations"
    assert payload["exit_code"] == 0
    assert result.exit_code == 0
