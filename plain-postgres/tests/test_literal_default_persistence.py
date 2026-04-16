"""Pin the schema-editor behavior for persistent literal `default=` values.

Literal (non-callable, non-None) defaults should be inlined into CREATE TABLE,
kept on ADD COLUMN, and preserved by the 4-way ALTER FIELD backfill. Callable
defaults, `update_now` auto-fills, and the synthesized empty-string default
for `required=False` text fields must continue to use the transient
ADD+DROP path.
"""

from __future__ import annotations

from typing import Any

from app.examples.models.defaults import DefaultsExample

from plain.postgres import fields as plain_fields
from plain.postgres import get_connection


def _db_type(field: Any) -> str:
    t = field.db_type()
    assert t is not None
    return t


def test_create_table_inlines_literal_default(db):
    """CREATE TABLE for a model with `default="pending"` emits `DEFAULT` on
    the column and leaves it there (no trailing DROP DEFAULT)."""
    connection = get_connection()
    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor.create_model(DefaultsExample)

    joined = " ".join(editor.executed_sql).lower()
    assert "default 'pending'" in joined
    assert "default 5" in joined
    assert "default 'auto'" in joined
    # Inlined in CREATE TABLE — no follow-up DROP DEFAULT needed.
    assert "drop default" not in joined


def test_add_field_keeps_literal_default(db):
    """add_field emits a single ADD COLUMN with DEFAULT and does NOT follow up
    with DROP DEFAULT for a literal default."""
    field = plain_fields.TextField(max_length=20, default="active")
    field.set_attributes_from_name("role")

    connection = get_connection()
    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor.add_field(DefaultsExample, field)

    joined = " ".join(editor.executed_sql).lower()
    assert "add column" in joined
    assert "default 'active'" in joined
    assert "drop default" not in joined


def test_add_field_without_default_emits_no_default_clause(db):
    """`required=False` without an explicit `default=` no longer auto-fills
    existing rows — the ADD COLUMN SQL carries no DEFAULT. The user has to
    declare `default=""` (persists) or `allow_null=True` (nullable column)."""
    field = plain_fields.TextField(max_length=10, required=False)
    field.set_attributes_from_name("tmp_required_false")

    connection = get_connection()
    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor.add_field(DefaultsExample, field)

    joined = " ".join(editor.executed_sql).lower()
    assert " default " not in joined
    assert "drop default" not in joined


def test_alter_field_nullable_to_not_null_keeps_literal_default(db):
    """The 4-way backfill does a no-op SET DEFAULT pass when old/new defaults
    are equal and leaves the persistent column DEFAULT alone — no DROP."""
    old_field = plain_fields.TextField(max_length=20, allow_null=True, default="active")
    old_field.set_attributes_from_name("role")
    new_field = plain_fields.TextField(max_length=20, default="active")
    new_field.set_attributes_from_name("role")

    connection = get_connection()
    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor._alter_field(
            DefaultsExample,
            old_field,
            new_field,
            old_type=_db_type(old_field),
            new_type=_db_type(new_field),
        )

    joined = " ".join(editor.executed_sql).lower()
    assert "set not null" in joined
    assert "drop default" not in joined


def test_alter_field_literal_default_change_skips_drop(db):
    """Changing `default=` alongside a nullable→NOT NULL transition runs the
    full 4-way backfill (SET DEFAULT new, UPDATE, SET NOT NULL). The trailing
    DROP DEFAULT is skipped because the new field declares a persistent
    literal default."""
    old_field = plain_fields.TextField(max_length=20, allow_null=True, default="active")
    old_field.set_attributes_from_name("role")
    new_field = plain_fields.TextField(max_length=20, default="paused")
    new_field.set_attributes_from_name("role")

    connection = get_connection()
    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor._alter_field(
            DefaultsExample,
            old_field,
            new_field,
            old_type=_db_type(old_field),
            new_type=_db_type(new_field),
        )

    joined = " ".join(editor.executed_sql).lower()
    assert "set default 'paused'" in joined
    assert "set not null" in joined
    assert "drop default" not in joined


def test_alter_field_default_only_change_is_migration_no_op(db):
    """Changing only ``default=`` on an already-NOT-NULL column emits nothing
    from the schema editor — ``default`` is in ``non_db_attrs``, so the
    migration path short-circuits. Convergence's ``_compare_column_default``
    detects CHANGED drift and applies ``SetColumnDefaultFix`` on the next sync
    (covered by ``test_detects_changed_literal_default``)."""
    old_field = plain_fields.TextField(max_length=20, default="active")
    old_field.set_attributes_from_name("role")
    new_field = plain_fields.TextField(max_length=20, default="paused")
    new_field.set_attributes_from_name("role")

    connection = get_connection()
    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor.alter_field(DefaultsExample, old_field, new_field)

    assert editor.executed_sql == []


def test_has_persistent_literal_default_predicate():
    """Unit coverage for the predicate that drives all of the above."""
    assert plain_fields.TextField(default="x").has_persistent_literal_default()
    assert plain_fields.IntegerField(default=0).has_persistent_literal_default()
    assert plain_fields.BooleanField(default=False).has_persistent_literal_default()
    assert not plain_fields.TextField().has_persistent_literal_default()
    assert not plain_fields.TextField(
        default=None, allow_null=True
    ).has_persistent_literal_default()
    # Fields that don't extend DefaultableField don't accept default= at all.
    assert not plain_fields.UUIDField().has_persistent_literal_default()
    assert not plain_fields.DateTimeField().has_persistent_literal_default()


def test_compile_literal_default_sql_handles_jsonfield(db):
    """JSONField with a literal default compiles to ``'<json>'::jsonb`` and
    round-trips cleanly through the convergence normalization."""
    from plain.postgres import JSONField
    from plain.postgres.ddl import compile_literal_default_sql
    from plain.postgres.introspection import normalize_default_sql

    field = JSONField(default={"x": 1})
    field.set_attributes_from_name("settings")

    sql = compile_literal_default_sql(field)
    assert "jsonb" in sql.lower()
    # Changing the value changes the normalized form — drift is detectable.
    other = JSONField(default={"x": 2})
    other.set_attributes_from_name("settings")
    other_sql = compile_literal_default_sql(other)
    assert normalize_default_sql(sql) != normalize_default_sql(other_sql)


def test_jsonb_defaults_equivalent_despite_key_reorder(db):
    """PG canonicalizes jsonb keys (length then lex), which reorders Python's
    insertion-order dump. A plain string compare would flag CHANGED every
    sync; _compare_column_default must use semantic JSON equality for
    jsonb defaults."""
    from plain.postgres.convergence.analysis import _defaults_equivalent

    # Same dict, PG-canonicalized vs Python insertion-order.
    model = '\'{"b": 1, "a": 2}\'::jsonb'
    db = '\'{"a": 2, "b": 1}\'::jsonb'
    assert _defaults_equivalent(model, db)

    # Genuinely different JSON still detected as CHANGED.
    model = "'{\"a\": 1}'::jsonb"
    db = "'{\"a\": 2}'::jsonb"
    assert not _defaults_equivalent(model, db)


def test_special_char_string_default_round_trip(isolated_db):
    """Literal string defaults with quotes, newlines, and other typical
    non-ASCII punctuation must survive the round trip: compile → SET DEFAULT
    → pg_get_expr → compare without drift. Otherwise every sync would flag
    CHANGED for safe-but-ugly inputs."""
    from conftest_convergence import column_default_sql, execute

    from plain.postgres.convergence.analysis import _defaults_equivalent
    from plain.postgres.ddl import compile_literal_default_sql

    cases = [
        "O'Reilly",  # single quote — psycopg escapes by doubling
        "line1\nline2",  # newline — standard strings carry it literally
        "tab\there",  # tab
        '"quoted"',  # double quotes
        "percent%sign",  # % isn't interpolated in DDL SET DEFAULT
        "",  # empty string
    ]

    for value in cases:
        field = plain_fields.TextField(max_length=100, default=value)
        field.set_attributes_from_name("status")

        expected_sql = compile_literal_default_sql(field)
        execute(
            'ALTER TABLE "examples_defaultsexample" '
            f'ALTER COLUMN "status" SET DEFAULT {expected_sql}'
        )

        actual_sql = column_default_sql("examples_defaultsexample", "status")
        assert actual_sql is not None
        assert _defaults_equivalent(expected_sql, actual_sql), (
            f"round-trip drift for default={value!r}: "
            f"compiled={expected_sql!r} catalog={actual_sql!r}"
        )


def test_backslash_in_string_default_rejected():
    """Backslashes force psycopg into ``E'...'`` escape syntax, which
    pg_get_expr returns as a plain ``'...'`` literal — the two forms don't
    round-trip, so convergence would flag spurious drift on every sync.
    DefaultableField rejects them at declaration time."""
    import pytest

    with pytest.raises(ValueError, match="backslash"):
        plain_fields.TextField(max_length=100, default=r"C:\Program Files")
