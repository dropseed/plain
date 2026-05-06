"""Pin Python-side `default=` field behavior for literal values.

Style: system-level — exercise real inserts and introspect the real schema.
"""

from __future__ import annotations

import psycopg
import pytest
from app.examples.models.defaults import DefaultsExample

from plain.postgres import get_connection


def _column_default(table_name: str, column_name: str) -> str | None:
    """Return the persisted column DEFAULT expression, or None."""
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            SELECT column_default
              FROM information_schema.columns
             WHERE table_name = %s AND column_name = %s
            """,
            [table_name, column_name],
        )
        row = cursor.fetchone()
    return row[0] if row else None


def test_static_string_default_applied_on_save(db):
    row = DefaultsExample.query.create(name="row")
    assert row.status == "pending"


def test_static_int_default_applied_on_save(db):
    row = DefaultsExample.query.create(name="row")
    assert row.priority == 5


def test_explicit_value_overrides_default(db):
    row = DefaultsExample.query.create(name="row", status="done", priority=99)
    assert row.status == "done"
    assert row.priority == 99


def test_static_defaults_persist_on_column(db):
    """Literal defaults are installed as the column's persistent DEFAULT so
    raw SQL INSERTs get them and convergence owns them uniformly alongside
    DB-expression defaults."""
    status_default = _column_default("examples_defaultsexample", "status")
    assert status_default is not None
    assert "pending" in status_default

    priority_default = _column_default("examples_defaultsexample", "priority")
    assert priority_default is not None
    assert "5" in priority_default


def test_queryset_update_does_not_touch_default_column(db):
    """`.filter(...).update(field=...)` only writes the named columns — the
    defaulted column is untouched and keeps its originally-inserted value."""
    row = DefaultsExample.query.create(name="row")
    original_status = row.status

    DefaultsExample.query.filter(id=row.id).update(name="updated")

    reloaded = DefaultsExample.query.get(id=row.id)
    assert reloaded.status == original_status
    assert reloaded.name == "updated"


def test_get_or_create_applies_default_only_on_create(db):
    row, created = DefaultsExample.query.get_or_create(name="only-once")
    assert created is True
    assert row.status == "pending"

    same, created_again = DefaultsExample.query.get_or_create(name="only-once")
    assert created_again is False
    assert same.status == "pending"


def test_explicit_none_on_nullable_overrides_default(db):
    """Passing `note=None` inserts NULL — it does NOT silently fall back to
    the `default="auto"`."""
    default_row = DefaultsExample.query.create(name="default")
    assert default_row.note == "auto"

    null_row = DefaultsExample.query.create(name="explicit-none", note=None)
    assert null_row.note is None

    # Round-trip through the DB to be sure it was persisted as NULL, not "auto".
    reloaded = DefaultsExample.query.get(id=null_row.id)
    assert reloaded.note is None


def test_refresh_from_db_reads_persisted_value_not_default(db):
    """After save, refresh_from_db reflects what's actually in the DB — even
    after an in-memory attribute has been stomped on."""
    row = DefaultsExample.query.create(name="row")

    row.status = "stomped"
    row.refresh_from_db()

    assert row.status == "pending"


def test_omitted_required_field_uses_python_empty_at_construction(db):
    """A required column field omitted at `Model()` construction takes the
    type's Python-side empty value (e.g. "" for text), not None. full_clean
    surfaces required-but-empty separately; this contract keeps non-validated
    save paths from sending NULL to a NOT NULL column for empty-string types.
    """
    row = DefaultsExample()
    # name is TextField(required=True) with no `default=` — empty string
    # fallback at construction.
    assert row.name == ""


def test_raw_insert_uses_persisted_literal_default(db):
    """A raw SQL INSERT that omits a column with a literal `default=` gets
    the value from the column's DEFAULT — the backstop the persistent column
    DEFAULT provides."""
    with get_connection().cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO examples_defaultsexample (name, priority)
            VALUES (%s, %s)
            RETURNING status, note
            """,
            ["raw", 1],
        )
        row = cursor.fetchone()
    assert row == ("pending", "auto")


def test_raw_insert_fails_when_required_column_has_no_default(db):
    """Columns without a literal/expression default still require a value."""
    with pytest.raises(psycopg.errors.NotNullViolation):
        with get_connection().cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO examples_defaultsexample (priority)
                VALUES (%s)
                """,
                [1],
            )
