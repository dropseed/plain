"""Assert that migration DDL emitted by the schema editor is wrapped with
``SET LOCAL lock_timeout`` / ``SET LOCAL statement_timeout`` derived from the
``POSTGRES_MIGRATION_*`` settings, and that ``RunSQL(no_timeout=True)`` opts
out.
"""

from __future__ import annotations

from typing import cast

import pytest
from app.examples.models.defaults import DefaultsExample

from plain.postgres import fields as plain_fields
from plain.postgres import get_connection
from plain.postgres.migrations.operations.special import RunSQL
from plain.runtime import settings as plain_settings


def _collect(callback, *, atomic: bool = True) -> list[str]:
    connection = get_connection()
    with connection.schema_editor(atomic=atomic, collect_sql=True) as editor:
        callback(editor)
    return editor.executed_sql


def test_execute_prepends_set_local_timeouts(db):
    sql_list = _collect(
        lambda editor: editor.execute(
            "ALTER TABLE examples_defaultsexample ADD COLUMN tmp_col integer"
        )
    )
    assert len(sql_list) == 1
    stmt = sql_list[0]
    assert stmt.startswith("SET LOCAL lock_timeout = '3s';")
    assert "SET LOCAL statement_timeout = '3s';" in stmt
    assert stmt.rstrip().endswith("ADD COLUMN tmp_col integer")


def test_set_timeouts_false_emits_no_prelude(db):
    sql_list = _collect(
        lambda editor: editor.execute(
            "ALTER TABLE examples_defaultsexample ADD COLUMN tmp_col integer",
            set_timeouts=False,
        )
    )
    assert len(sql_list) == 1
    assert "SET LOCAL" not in sql_list[0]


def test_timeout_values_propagate_from_settings(db, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plain_settings, "POSTGRES_MIGRATION_LOCK_TIMEOUT", "750ms")
    monkeypatch.setattr(plain_settings, "POSTGRES_MIGRATION_STATEMENT_TIMEOUT", "5s")

    sql_list = _collect(
        lambda editor: editor.execute(
            "ALTER TABLE examples_defaultsexample ADD COLUMN tmp_col integer"
        )
    )
    stmt = sql_list[0]
    assert "lock_timeout = '750ms'" in stmt
    assert "statement_timeout = '5s'" in stmt


def test_create_model_wraps_each_statement(db):
    sql_list = _collect(lambda editor: editor.create_model(DefaultsExample))
    assert sql_list  # not empty
    for stmt in sql_list:
        assert stmt.startswith("SET LOCAL lock_timeout = '3s';")
        assert "SET LOCAL statement_timeout = '3s';" in stmt


def test_alter_field_backfill_update_carries_statement_timeout(db):
    """The 4-way backfill UPDATE runs under ACCESS EXCLUSIVE; it intentionally
    inherits the 3s statement_timeout. Confirm the prelude is on the UPDATE."""
    old_field = plain_fields.TextField(max_length=20, allow_null=True, default="active")
    old_field.set_attributes_from_name("role")
    new_field = plain_fields.TextField(max_length=20, default="active")
    new_field.set_attributes_from_name("role")

    connection = get_connection()
    with connection.schema_editor(atomic=True, collect_sql=True) as editor:
        editor._alter_field(
            DefaultsExample,
            old_field,
            new_field,
            old_type="character varying(20)",
            new_type="character varying(20)",
        )

    update_stmts = [s for s in editor.executed_sql if " UPDATE " in f" {s} "]
    assert update_stmts, "expected at least one backfill UPDATE"
    for stmt in update_stmts:
        assert stmt.startswith("SET LOCAL lock_timeout = '3s';")
        assert "SET LOCAL statement_timeout = '3s';" in stmt


def test_non_atomic_migration_skips_set_local(db):
    """SET LOCAL is a no-op with WARNING outside a transaction block, so the
    schema editor must skip the prelude when opened with atomic=False
    (e.g. a migration that uses RunSQL to issue CONCURRENTLY). Without this
    gate, users would assume timeouts applied when they silently didn't."""
    sql_list = _collect(
        lambda editor: editor.execute(
            "ALTER TABLE examples_defaultsexample ADD COLUMN tmp_col integer"
        ),
        atomic=False,
    )
    assert len(sql_list) == 1
    assert "SET LOCAL" not in sql_list[0]


def test_runsql_no_timeout_opts_out(db):
    """`RunSQL(no_timeout=True)` disables the SET LOCAL prelude entirely so a
    long-running data migration can run without a statement_timeout."""
    connection = get_connection()
    # cast: Operation.__new__ is annotated `-> Operation`, so ty infers the
    # widened type for every subclass constructor. Narrows back to RunSQL
    # so `._run_sql` / `.sql` access type-checks.
    op = cast(
        RunSQL,
        RunSQL(
            "UPDATE examples_defaultsexample SET role = role",
            no_timeout=True,
        ),
    )

    with connection.schema_editor(atomic=True, collect_sql=True) as editor:
        op._run_sql(editor, op.sql)

    assert len(editor.executed_sql) == 1
    assert "SET LOCAL" not in editor.executed_sql[0]


def test_runsql_default_applies_timeouts(db):
    """Without `no_timeout=True`, RunSQL DDL gets the migration timeouts."""
    connection = get_connection()
    op = cast(RunSQL, RunSQL("UPDATE examples_defaultsexample SET role = role"))

    with connection.schema_editor(atomic=True, collect_sql=True) as editor:
        op._run_sql(editor, op.sql)

    stmt = editor.executed_sql[0]
    assert stmt.startswith("SET LOCAL lock_timeout = '3s';")
    assert "SET LOCAL statement_timeout = '3s';" in stmt


def test_runsql_no_timeout_serializes_in_deconstruct():
    """`no_timeout=True` survives migration serialization; default is omitted."""
    assert RunSQL("SELECT 1").deconstruct() == ("RunSQL", (), {"sql": "SELECT 1"})
    assert RunSQL("SELECT 1", no_timeout=True).deconstruct() == (
        "RunSQL",
        (),
        {"sql": "SELECT 1", "no_timeout": True},
    )
