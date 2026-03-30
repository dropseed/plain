from __future__ import annotations

import psycopg
import pytest

from plain.postgres import get_connection
from plain.postgres.migrations.executor import MigrationExecutor
from plain.postgres.migrations.migration import Migration
from plain.postgres.migrations.operations.special import RunSQL
from plain.postgres.migrations.recorder import MigrationRecorder


def _table_exists(table_name: str) -> bool:
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
            [table_name],
        )
        return cursor.fetchone() is not None


def _migration_is_recorded(package_label: str, name: str) -> bool:
    recorder = MigrationRecorder(get_connection())
    return (package_label, name) in recorder.applied_migrations()


def _clean_up_migration_record(package_label: str, name: str) -> None:
    recorder = MigrationRecorder(get_connection())
    recorder.record_unapplied(package_label, name)


def _clean_up_table(table_name: str) -> None:
    with get_connection().cursor() as cursor:
        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')


class TestMigrationTransactionAtomicity:
    """Schema changes and migration record are atomic — both commit or both roll back."""

    def test_successful_migration_records_and_applies(self, db):
        """A successful migration commits both schema changes and the migration record."""
        migration = Migration("test_success", "examples")
        migration.operations = [
            RunSQL(sql='CREATE TABLE "test_executor_success" (id bigint PRIMARY KEY)'),
        ]

        executor = MigrationExecutor(get_connection())
        try:
            executor.apply_migration(executor.loader.project_state(), migration)

            assert _table_exists("test_executor_success")
            assert _migration_is_recorded("examples", "test_success")
        finally:
            _clean_up_table("test_executor_success")
            _clean_up_migration_record("examples", "test_success")

    def test_failed_migration_rolls_back_both(self, db):
        """A failed migration rolls back schema changes and does not record."""
        migration = Migration("test_failure", "examples")
        migration.operations = [
            RunSQL(
                sql=[
                    'CREATE TABLE "test_executor_failure" (id bigint PRIMARY KEY)',
                    "SELECT 1 / 0",  # Division by zero — will fail
                ]
            ),
        ]

        executor = MigrationExecutor(get_connection())
        with pytest.raises(psycopg.errors.DivisionByZero):
            executor.apply_migration(executor.loader.project_state(), migration)

        # Both the table creation and the migration record should be rolled back
        assert not _table_exists("test_executor_failure")
        assert not _migration_is_recorded("examples", "test_failure")

    def test_fake_migration_records_without_schema_changes(self, db):
        """A fake migration records the migration without touching the database."""
        migration = Migration("test_fake", "examples")
        migration.operations = [
            RunSQL(sql='CREATE TABLE "test_executor_fake" (id bigint PRIMARY KEY)'),
        ]

        executor = MigrationExecutor(get_connection())
        try:
            executor.apply_migration(
                executor.loader.project_state(), migration, fake=True
            )

            assert not _table_exists("test_executor_fake")
            assert _migration_is_recorded("examples", "test_fake")
        finally:
            _clean_up_migration_record("examples", "test_fake")
