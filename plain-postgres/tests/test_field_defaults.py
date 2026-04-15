"""Pin current `default=` field behavior before fields-db-defaults Phase 1.

These tests lock in today's Python-side-default semantics so we can detect
regressions as we add DB-expression default support (`default=Now()`,
`default=GenRandomUUID()`).

Style: system-level — exercise real inserts and introspect the real schema.
"""

from __future__ import annotations

import uuid

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
    """`default=uuid.uuid4` produces a unique value for each saved row."""
    a = DefaultsExample.query.create(name="a")
    b = DefaultsExample.query.create(name="b")

    assert isinstance(a.token_uuid, uuid.UUID)
    assert isinstance(b.token_uuid, uuid.UUID)
    assert a.token_uuid != b.token_uuid


def test_callable_default_unique_across_bulk_create(db):
    """bulk_create evaluates the callable default per row (Python-side)."""
    rows = DefaultsExample.query.bulk_create(
        [DefaultsExample(name=f"row-{i}") for i in range(5)]
    )

    uuids = {r.token_uuid for r in rows}
    assert len(uuids) == 5, "every bulk_created row should get a unique UUID"


def test_static_string_default_applied_on_save(db):
    row = DefaultsExample.query.create(name="row")
    assert row.status == "pending"


def test_static_int_default_applied_on_save(db):
    row = DefaultsExample.query.create(name="row")
    assert row.priority == 5


def test_explicit_value_overrides_default(db):
    explicit = uuid.uuid4()
    row = DefaultsExample.query.create(
        name="row", token_uuid=explicit, status="done", priority=99
    )
    assert row.token_uuid == explicit
    assert row.status == "done"
    assert row.priority == 99


def test_callable_default_does_not_persist_on_column(db):
    """Current behavior: callable defaults are evaluated at migration time and
    the resulting column DEFAULT is dropped after CREATE TABLE. A raw SQL
    INSERT that omits the column therefore receives NULL (or fails), because
    the database is not asked to produce a value.

    This test pins that behavior so we can flip the expectation in Phase 1
    for BaseExpression defaults (which WILL persist)."""
    assert _column_default("examples_defaultsexample", "token_uuid") is None


def test_static_defaults_also_not_persisted_on_column(db):
    """Plain treats ALL Python defaults the same way today — even constants
    are not kept as column DEFAULTs. This documents that."""
    assert _column_default("examples_defaultsexample", "status") is None
    assert _column_default("examples_defaultsexample", "priority") is None


def test_update_does_not_re_apply_callable_default(db):
    """Defaults fire on insert, never on update. bulk_update must preserve
    existing UUIDs — this is what the Phase 1 sentinel MUST NOT leak into."""
    rows = DefaultsExample.query.bulk_create(
        [DefaultsExample(name=f"row-{i}") for i in range(3)]
    )
    original_uuids = [r.token_uuid for r in rows]

    # Mutate a non-default field and save.
    for r in rows:
        r.name = r.name.upper()
    DefaultsExample.query.bulk_update(rows, ["name"])

    refreshed = list(DefaultsExample.query.order_by("id"))
    assert [r.token_uuid for r in refreshed] == original_uuids
    assert [r.name for r in refreshed] == ["ROW-0", "ROW-1", "ROW-2"]


def test_queryset_update_does_not_touch_default_column(db):
    """`.filter(...).update(field=...)` only writes the named columns — the
    defaulted column is untouched and keeps its originally-inserted value."""
    row = DefaultsExample.query.create(name="row")
    original_uuid = row.token_uuid

    DefaultsExample.query.filter(id=row.id).update(name="updated")

    reloaded = DefaultsExample.query.get(id=row.id)
    assert reloaded.token_uuid == original_uuid
    assert reloaded.name == "updated"


def test_get_or_create_applies_default_only_on_create(db):
    row, created = DefaultsExample.query.get_or_create(name="only-once")
    assert created is True
    first_uuid = row.token_uuid
    assert row.status == "pending"

    same, created_again = DefaultsExample.query.get_or_create(name="only-once")
    assert created_again is False
    assert same.token_uuid == first_uuid
    assert same.status == "pending"


def test_explicit_none_on_nullable_overrides_default(db):
    """Passing `note=None` inserts NULL — it does NOT silently fall back to
    the `default="auto"`. Phase 1's DATABASE_DEFAULT sentinel must detect
    "kwarg absent" distinctly from "kwarg is None"."""
    default_row = DefaultsExample.query.create(name="default")
    assert default_row.note == "auto"

    null_row = DefaultsExample.query.create(name="explicit-none", note=None)
    assert null_row.note is None

    # Round-trip through the DB to be sure it was persisted as NULL, not "auto".
    reloaded = DefaultsExample.query.get(id=null_row.id)
    assert reloaded.note is None


def test_refresh_from_db_reads_persisted_value_not_default(db):
    """After save, refresh_from_db reflects what's actually in the DB —
    important because Phase 1's RETURNING populate-back path needs to agree
    with what refresh_from_db would produce."""
    row = DefaultsExample.query.create(name="row")
    original_uuid = row.token_uuid

    # Stomp on the in-memory attribute; refresh should restore the real value.
    row.token_uuid = uuid.uuid4()
    row.refresh_from_db()

    assert row.token_uuid == original_uuid


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

    This is the gap fields-db-defaults Phase 1 closes for expression defaults.
    """
    with pytest.raises(psycopg.errors.NotNullViolation):
        with get_connection().cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO examples_defaultsexample (name, token_uuid, priority)
                VALUES (%s, %s, %s)
                """,
                ["raw", uuid.uuid4(), 1],
            )
