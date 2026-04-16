"""Pin Python-side `default=` field behavior (callable and static values).

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


def test_callable_default_evaluated_per_instance_on_save(db):
    """`default=_make_token` produces a unique value for each saved row."""
    a = DefaultsExample.query.create(name="a")
    b = DefaultsExample.query.create(name="b")

    assert isinstance(a.token, str)
    assert isinstance(b.token, str)
    assert a.token != b.token


def test_callable_default_unique_across_bulk_create(db):
    """bulk_create evaluates the callable default per row (Python-side)."""
    rows = DefaultsExample.query.bulk_create(
        [DefaultsExample(name=f"row-{i}") for i in range(5)]
    )

    tokens = {r.token for r in rows}
    assert len(tokens) == 5, "every bulk_created row should get a unique token"


def test_static_string_default_applied_on_save(db):
    row = DefaultsExample.query.create(name="row")
    assert row.status == "pending"


def test_static_int_default_applied_on_save(db):
    row = DefaultsExample.query.create(name="row")
    assert row.priority == 5


def test_explicit_value_overrides_default(db):
    explicit = "explicit-token-value"
    row = DefaultsExample.query.create(
        name="row", token=explicit, status="done", priority=99
    )
    assert row.token == explicit
    assert row.status == "done"
    assert row.priority == 99


def test_callable_default_does_not_persist_on_column(db):
    """Callable defaults are evaluated at migration time and the resulting
    column DEFAULT is dropped after CREATE TABLE. A raw SQL INSERT that
    omits the column therefore receives NULL (or fails), because the database
    is not asked to produce a value.

    DB-expression defaults (`create_now=True`, `generate=True`) take a
    different path — those DO persist on the column."""
    assert _column_default("examples_defaultsexample", "token") is None


def test_static_defaults_also_not_persisted_on_column(db):
    """Plain treats ALL Python defaults the same way today — even constants
    are not kept as column DEFAULTs. This documents that."""
    assert _column_default("examples_defaultsexample", "status") is None
    assert _column_default("examples_defaultsexample", "priority") is None


def test_update_does_not_re_apply_callable_default(db):
    """Defaults fire on insert, never on update. bulk_update must preserve
    existing values."""
    rows = DefaultsExample.query.bulk_create(
        [DefaultsExample(name=f"row-{i}") for i in range(3)]
    )
    original_tokens = [r.token for r in rows]

    # Mutate a non-default field and save.
    for r in rows:
        r.name = r.name.upper()
    DefaultsExample.query.bulk_update(rows, ["name"])

    refreshed = list(DefaultsExample.query.order_by("id"))
    assert [r.token for r in refreshed] == original_tokens
    assert [r.name for r in refreshed] == ["ROW-0", "ROW-1", "ROW-2"]


def test_queryset_update_does_not_touch_default_column(db):
    """`.filter(...).update(field=...)` only writes the named columns — the
    defaulted column is untouched and keeps its originally-inserted value."""
    row = DefaultsExample.query.create(name="row")
    original_token = row.token

    DefaultsExample.query.filter(id=row.id).update(name="updated")

    reloaded = DefaultsExample.query.get(id=row.id)
    assert reloaded.token == original_token
    assert reloaded.name == "updated"


def test_get_or_create_applies_default_only_on_create(db):
    row, created = DefaultsExample.query.get_or_create(name="only-once")
    assert created is True
    first_token = row.token
    assert row.status == "pending"

    same, created_again = DefaultsExample.query.get_or_create(name="only-once")
    assert created_again is False
    assert same.token == first_token
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
    """After save, refresh_from_db reflects what's actually in the DB."""
    row = DefaultsExample.query.create(name="row")
    original_token = row.token

    # Stomp on the in-memory attribute; refresh should restore the real value.
    row.token = "stomped"
    row.refresh_from_db()

    assert row.token == original_token


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


def test_raw_insert_omitting_defaulted_column_fails_without_column_default(db):
    """Sanity check that backs up the previous tests: a pure-SQL INSERT that
    skips `status` errors out — the column has no DEFAULT and is NOT NULL, so
    Postgres itself cannot fill it. Plain's ORM fills the value in Python
    before sending the INSERT; the database is never asked.

    Expression defaults (`create_now=True`, `generate=True`) take a different
    path — those DO persist on the column and raw INSERT works.
    """
    with pytest.raises(psycopg.errors.NotNullViolation):
        with get_connection().cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO examples_defaultsexample (name, token, priority)
                VALUES (%s, %s, %s)
                """,
                ["raw", "t", 1],
            )
