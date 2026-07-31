"""Pin the schema-editor behavior for persistent literal `default=` values.

Literal (non-callable, non-None) defaults are inlined into CREATE TABLE and
kept on ADD COLUMN. Callable defaults, `update_now` auto-fills, and the
synthesized empty-string default for `required=False` text fields must
continue to use the transient ADD+DROP path. Nullability and column DEFAULT
changes on existing columns are convergence-managed — the schema editor
short-circuits on allow_null and default differences.
"""

from __future__ import annotations

from app.examples.models.defaults import DefaultsExample

from plain.postgres import fields as plain_fields
from plain.postgres import get_connection


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


def test_alter_field_nullable_to_not_null_is_migration_no_op(db):
    """allow_null is in non_migration_attrs — the schema editor emits nothing for a
    nullable→NOT NULL transition. Convergence owns the CHECK NOT VALID +
    VALIDATE + SET NOT NULL dance on the next sync."""
    old_field = plain_fields.TextField(max_length=20, allow_null=True, default="active")
    old_field.set_attributes_from_name("role")
    new_field = plain_fields.TextField(max_length=20, default="active")
    new_field.set_attributes_from_name("role")

    connection = get_connection()
    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor.alter_field(DefaultsExample, old_field, new_field)

    assert editor.executed_sql == []


def test_alter_field_literal_default_change_with_null_flip_is_migration_no_op(db):
    """Flipping allow_null AND changing default= emits nothing from the schema
    editor. Both attributes are in non_migration_attrs, and convergence handles the
    column DEFAULT drift + NOT NULL transition independently on the next sync."""
    old_field = plain_fields.TextField(max_length=20, allow_null=True, default="active")
    old_field.set_attributes_from_name("role")
    new_field = plain_fields.TextField(max_length=20, default="paused")
    new_field.set_attributes_from_name("role")

    connection = get_connection()
    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor.alter_field(DefaultsExample, old_field, new_field)

    assert editor.executed_sql == []


def test_alter_field_default_only_change_is_migration_no_op(db):
    """Changing only ``default=`` on an already-NOT-NULL column emits nothing
    from the schema editor — ``default`` is in ``non_migration_attrs``, so the
    migration path short-circuits. Convergence's ``_compare_column_default``
    detects CHANGED drift and applies ``SetColumnDefaultCorrection`` on the next sync
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
    assert not plain_fields.UUIDField().has_persistent_literal_default()
    assert not plain_fields.DateTimeField().has_persistent_literal_default()
    # ColumnField-direct fields accept only default=None (the nullable-optional
    # marker for typed construction), which is never a persistent literal.
    assert not plain_fields.UUIDField(
        allow_null=True, default=None
    ).has_persistent_literal_default()
    assert not plain_fields.BinaryField(
        allow_null=True, default=None
    ).has_persistent_literal_default()
    from plain.postgres.fields.encrypted import (
        EncryptedJSONField,
        EncryptedTextField,
    )

    assert not EncryptedTextField(
        allow_null=True, default=None
    ).has_persistent_literal_default()
    assert not EncryptedJSONField(
        allow_null=True, default=None
    ).has_persistent_literal_default()


def test_compile_literal_default_sql_handles_jsonfield():
    """JSONField with a literal default compiles to ``'<json>'::jsonb`` —
    different values produce different SQL so drift is detectable."""
    from plain.postgres import JSONField
    from plain.postgres.ddl import compile_literal_default_sql

    field = JSONField(default={"x": 1})
    field.set_attributes_from_name("settings")

    sql = compile_literal_default_sql(field)
    assert "jsonb" in sql.lower()

    other = JSONField(default={"x": 2})
    other.set_attributes_from_name("settings")
    other_sql = compile_literal_default_sql(other)
    assert sql != other_sql


def test_special_char_string_default_round_trip(isolated_db):
    """Literal string defaults with quotes, newlines, and other typical
    non-ASCII punctuation must survive the round trip: compile → SET DEFAULT
    → pg_get_expr → normalize the model side → compare. Otherwise every
    sync would flag CHANGED for safe-but-ugly inputs."""
    from conftest_convergence import column_default_sql, execute

    from plain.postgres.convergence.analysis import _normalize_default_expr
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
        connection = get_connection()
        with connection.cursor() as cursor:
            normalized_expected = _normalize_default_expr(
                cursor, DefaultsExample, "status", expected_sql
            )
        assert normalized_expected == actual_sql, (
            f"round-trip drift for default={value!r}: "
            f"compiled={expected_sql!r} normalized={normalized_expected!r} "
            f"catalog={actual_sql!r}"
        )


def test_jsonb_default_no_drift_when_keys_reordered(isolated_db):
    """A JSONField default whose Python source key order differs from the
    DB-stored literal must not flag drift. pg_get_expr deparses literal
    nodes verbatim, so source-order changes in the model leak straight
    through the round-trip — only the JSON-semantic fallback in
    `_compare_column_default` keeps these in sync. Without that fallback,
    every sync of a JSONField default whose author rearranged keys would
    report spurious CHANGED."""
    from conftest_convergence import execute

    from plain.postgres import JSONField
    from plain.postgres.convergence.analysis import _compare_column_default
    from plain.postgres.introspection import ColumnState, introspect_table

    table = "_test_jsonb_default_table"
    # DB stores the default with one key order.
    execute(
        f'CREATE TABLE "{table}" '
        "(id integer PRIMARY KEY, "
        "settings jsonb NOT NULL "
        'DEFAULT \'{"b": 1, "a": 2}\'::jsonb)'
    )
    try:

        class FakeModel:
            class model_options:
                db_table = table

        # Same JSON values, different Python source key order than the DB.
        field = JSONField(default={"a": 2, "b": 1})
        field.set_attributes_from_name("settings")
        field.model = FakeModel  # ty: ignore[invalid-assignment]

        connection = get_connection()
        with connection.cursor() as cursor:
            actual_default = (
                introspect_table(connection, cursor, table)
                .columns["settings"]
                .default_sql
            )
        assert actual_default is not None
        actual = ColumnState(type="jsonb", not_null=True, default_sql=actual_default)

        with connection.cursor() as cursor:
            result = _compare_column_default(cursor, field, actual, table)

        assert result is None, (
            f"Spurious drift for semantically equal jsonb defaults: "
            f"model={{'a': 2, 'b': 1}}, db default_sql={actual_default!r}"
        )
    finally:
        execute(f'DROP TABLE IF EXISTS "{table}"')


def test_jsonb_default_drift_when_values_differ(isolated_db):
    """The JSON-semantic fallback resolves *key order*, not value drift —
    a JSONField whose default value really differs from the DB literal
    must still report CHANGED. Pins the negative case so the fallback
    can't drift into a "never reports JSONField drift" bug."""
    from conftest_convergence import execute

    from plain.postgres import JSONField
    from plain.postgres.convergence.analysis import (
        ColumnDefaultDrift,
        DriftKind,
        _compare_column_default,
    )
    from plain.postgres.introspection import ColumnState, introspect_table

    table = "_test_jsonb_default_drift_table"
    execute(
        f'CREATE TABLE "{table}" '
        "(id integer PRIMARY KEY, "
        "settings jsonb NOT NULL "
        "DEFAULT '{\"a\": 1}'::jsonb)"
    )
    try:

        class FakeModel:
            class model_options:
                db_table = table

        # Genuinely different value — `a: 2` vs DB's `a: 1`.
        field = JSONField(default={"a": 2})
        field.set_attributes_from_name("settings")
        field.model = FakeModel  # ty: ignore[invalid-assignment]

        connection = get_connection()
        with connection.cursor() as cursor:
            actual_default = (
                introspect_table(connection, cursor, table)
                .columns["settings"]
                .default_sql
            )
        assert actual_default is not None
        actual = ColumnState(type="jsonb", not_null=True, default_sql=actual_default)

        with connection.cursor() as cursor:
            result = _compare_column_default(cursor, field, actual, table)

        assert isinstance(result, ColumnDefaultDrift)
        assert result.kind == DriftKind.CHANGED
    finally:
        execute(f'DROP TABLE IF EXISTS "{table}"')


def test_backslash_in_string_default_rejected():
    """Backslashes force psycopg into ``E'...'`` escape syntax, which
    pg_get_expr returns as a plain ``'...'`` literal — the two forms don't
    round-trip, so convergence would flag spurious drift on every sync.
    DefaultableField rejects them at declaration time."""
    import pytest

    with pytest.raises(ValueError, match="backslash"):
        plain_fields.TextField(max_length=100, default=r"C:\Program Files")
