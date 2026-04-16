"""Tests for DB-expression defaults (`DateTimeField(create_now=True)`,
`UUIDField(generate=True)`).

Covers:
- DDL: column DEFAULT persists after CREATE TABLE
- Raw SQL: INSERT omitting the column triggers the DB default
- ORM: Model().save() + bulk_create() populate via RETURNING
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import pytest
from app.examples.models.defaults import DBDefaultsExample, DefaultsExample

from plain.postgres import get_connection
from plain.postgres.fields import DATABASE_DEFAULT
from plain.postgres.functions import GenRandomUUID, Now


def _db_type(field: Any) -> str:
    """Thin narrower: field.db_type() returns `str | None` but _alter_field
    requires `str`. All of our test fields are concrete columns, so we just
    assert and pass the narrowed value."""
    t = field.db_type()
    assert t is not None
    return t


def _column_default(table_name: str, column_name: str) -> str | None:
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


def test_gen_random_uuid_default_persists_on_column(db):
    default = _column_default("examples_dbdefaultsexample", "db_uuid")
    assert default is not None
    assert "gen_random_uuid()" in default


def test_now_default_persists_on_column(db):
    default = _column_default("examples_dbdefaultsexample", "created_at")
    assert default is not None
    assert "statement_timestamp()" in default.lower()


def test_raw_insert_omitting_expression_defaulted_columns_succeeds(db):
    """The whole point of expression defaults: Postgres fills the value."""
    with get_connection().cursor() as cursor:
        cursor.execute(
            "INSERT INTO examples_dbdefaultsexample (name) VALUES (%s) "
            "RETURNING db_uuid, created_at",
            ["raw-row"],
        )
        row = cursor.fetchone()

    assert row is not None
    assert isinstance(row[0], uuid.UUID)
    assert row[1] is not None


def test_raw_insert_produces_unique_uuids(db):
    """`gen_random_uuid()` runs per row, not once — the `ADD COLUMN default`
    bug this design fixes."""
    uuids = []
    with get_connection().cursor() as cursor:
        for i in range(5):
            cursor.execute(
                "INSERT INTO examples_dbdefaultsexample (name) VALUES (%s) "
                "RETURNING db_uuid",
                [f"row-{i}"],
            )
            row = cursor.fetchone()
            assert row is not None
            uuids.append(row[0])

    assert len(set(uuids)) == 5


def test_unsaved_instance_holds_sentinel(db):
    """Before save, attribute access returns the DATABASE_DEFAULT sentinel
    rather than evaluating the expression in Python."""
    inst = DBDefaultsExample(name="x")
    assert inst.db_uuid is DATABASE_DEFAULT
    assert inst.created_at is DATABASE_DEFAULT


def test_save_populates_value_via_returning(db):
    inst = DBDefaultsExample(name="saved")
    inst.save()

    assert isinstance(inst.db_uuid, uuid.UUID)
    assert isinstance(inst.created_at, datetime.datetime)
    assert inst.id is not None


def test_save_persists_to_database(db):
    inst = DBDefaultsExample(name="saved")
    inst.save()

    reloaded = DBDefaultsExample.query.get(id=inst.id)
    assert reloaded.db_uuid == inst.db_uuid
    assert reloaded.created_at == inst.created_at


def test_bulk_create_assigns_unique_values_per_row(db):
    rows = DBDefaultsExample.query.bulk_create(
        [DBDefaultsExample(name=f"b-{i}") for i in range(5)]
    )

    assert len({r.db_uuid for r in rows}) == 5
    for r in rows:
        assert isinstance(r.db_uuid, uuid.UUID)
        assert isinstance(r.created_at, datetime.datetime)
        assert r.id is not None


def test_explicit_value_overrides_db_default(db):
    explicit = uuid.UUID("11111111-2222-3333-4444-555555555555")
    explicit_dt = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)

    inst = DBDefaultsExample(name="explicit", db_uuid=explicit, created_at=explicit_dt)
    inst.save()

    assert inst.db_uuid == explicit
    assert inst.created_at == explicit_dt

    reloaded = DBDefaultsExample.query.get(id=inst.id)
    assert reloaded.db_uuid == explicit


def test_update_does_not_re_apply_db_default(db):
    """After the row exists, updating an unrelated field must not cause
    Postgres (or the ORM) to re-evaluate the DEFAULT expression."""
    inst = DBDefaultsExample(name="row")
    inst.save()
    original_uuid = inst.db_uuid

    DBDefaultsExample.query.filter(id=inst.id).update(name="renamed")

    reloaded = DBDefaultsExample.query.get(id=inst.id)
    assert reloaded.db_uuid == original_uuid
    assert reloaded.name == "renamed"


def test_refresh_from_db_returns_persisted_value(db):
    inst = DBDefaultsExample(name="row")
    inst.save()
    original_uuid = inst.db_uuid

    inst.db_uuid = uuid.uuid4()
    inst.refresh_from_db()

    assert inst.db_uuid == original_uuid


def test_full_clean_skips_constraints_on_sentinel_fields(db):
    """A UniqueConstraint over an expression-default field shouldn't trigger
    a SELECT lookup using the sentinel during save's full_clean — the value
    doesn't exist in Python yet."""
    inst = DBDefaultsExample(name="constrained")
    # If validate_constraints didn't exclude the sentinel field, this would
    # raise (UUIDField rejects non-UUID values) before the INSERT could run.
    inst.full_clean()
    inst.save()
    assert isinstance(inst.db_uuid, uuid.UUID)


def test_alter_field_is_no_op_for_default_only_expression_change(db):
    """AlterField that only changes an expression default must be a no-op in
    the schema editor — convergence reconciles the column DEFAULT afterward.
    This keeps the schema editor focused on table/column structure and lets
    the convergence engine own drift correction for persistent DEFAULTs."""
    from plain.postgres import fields as plain_fields

    connection = get_connection()

    # Adding an expression default: schema editor emits nothing.
    old_field = plain_fields.UUIDField()
    old_field.set_attributes_from_name("token")
    new_field = plain_fields.UUIDField(generate=True)
    new_field.set_attributes_from_name("token")

    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor._alter_field(
            DBDefaultsExample,
            old_field,
            new_field,
            old_type=_db_type(old_field),
            new_type=_db_type(new_field),
        )

    joined = " ".join(editor.executed_sql).lower()
    assert "set default" not in joined
    assert "drop default" not in joined

    # Removing an expression default: also no-op (user must take a data
    # migration to DROP DEFAULT; convergence treats unmanaged DB DEFAULTs as
    # out of scope).
    old_field = plain_fields.UUIDField(generate=True)
    old_field.set_attributes_from_name("token")
    new_field = plain_fields.UUIDField()
    new_field.set_attributes_from_name("token")

    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor._alter_field(
            DBDefaultsExample,
            old_field,
            new_field,
            old_type=_db_type(old_field),
            new_type=_db_type(new_field),
        )

    joined = " ".join(editor.executed_sql).lower()
    assert "set default" not in joined
    assert "drop default" not in joined


def test_alter_field_introducing_expression_default_with_not_null_raises(db):
    """Introducing an expression default in the SAME migration as a
    null→not-null transition is rejected — the 4-step backfill would write
    NULLs because effective_default returns None for expression defaults."""
    from plain.postgres import fields as plain_fields

    connection = get_connection()

    old_field = plain_fields.UUIDField(allow_null=True, required=False)
    old_field.set_attributes_from_name("token")
    new_field = plain_fields.UUIDField(generate=True)
    new_field.set_attributes_from_name("token")

    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        with pytest.raises(NotImplementedError, match="same migration"):
            editor._alter_field(
                DBDefaultsExample,
                old_field,
                new_field,
                old_type=_db_type(old_field),
                new_type=_db_type(new_field),
            )


def test_alter_field_not_null_after_existing_expression_default_succeeds(db):
    """Once the expression default already lives on the column, a follow-up
    migration that adds NOT NULL must succeed — the four-way dance backfills
    NULL rows by evaluating the column's DEFAULT, then SET NOT NULL."""
    from plain.postgres import fields as plain_fields

    connection = get_connection()

    # Same expression default on both sides; only allow_null changes.
    old_field = plain_fields.UUIDField(allow_null=True, generate=True)
    old_field.set_attributes_from_name("token")
    new_field = plain_fields.UUIDField(generate=True)
    new_field.set_attributes_from_name("token")

    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor._alter_field(
            DBDefaultsExample,
            old_field,
            new_field,
            old_type=_db_type(old_field),
            new_type=_db_type(new_field),
        )

    joined = " ".join(editor.executed_sql).lower()
    assert "set not null" in joined
    # NULL backfill must use literal DEFAULT so Postgres evaluates the
    # column's expression per row, not pass NULL as a parameter.
    assert "= default where" in joined
    assert "set token = null" not in joined


def test_alter_field_renames_column_before_dropping_old_default(db):
    """When AlterField both renames the column AND changes its type and the
    old field had an expression default, the DROP DEFAULT must use the new
    column name (run after the rename) — otherwise it targets a column
    that doesn't exist yet."""
    from plain.postgres import fields as plain_fields

    connection = get_connection()

    old_field = plain_fields.DateTimeField(create_now=True)
    old_field.set_attributes_from_name("touched_at")
    old_field.column = "old_touched_at"
    new_field = plain_fields.UUIDField(generate=True)
    new_field.set_attributes_from_name("touched_at")
    new_field.column = "new_touched_at"

    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor._alter_field(
            DBDefaultsExample,
            old_field,
            new_field,
            old_type=_db_type(old_field),
            new_type=_db_type(new_field),
        )

    statements = [s.lower() for s in editor.executed_sql]
    rename_idx = next((i for i, s in enumerate(statements) if "rename column" in s), -1)
    drop_idx = next((i for i, s in enumerate(statements) if "drop default" in s), -1)

    assert rename_idx >= 0, "expected a RENAME COLUMN statement"
    assert drop_idx > rename_idx, "DROP DEFAULT must come after RENAME COLUMN"
    # The DROP must target the new column name, not the old.
    assert "new_touched_at" in statements[drop_idx]
    assert "old_touched_at" not in statements[drop_idx]


def test_alter_field_sets_new_default_before_null_backfill(db):
    """When the four-way alteration runs with an expression default, the
    SET DEFAULT for the NEW expression must land before the UPDATE backfill
    so `UPDATE col = DEFAULT` evaluates the new expression, not whatever
    the column previously had (or nothing, if a type change just dropped it)."""
    from plain.postgres import fields as plain_fields

    connection = get_connection()

    # nullable → NOT NULL transition with an expression default on both sides.
    # The schema editor must SET DEFAULT the expression before backfilling.
    old_field = plain_fields.DateTimeField(allow_null=True, create_now=True)
    old_field.set_attributes_from_name("touched_at")
    new_field = plain_fields.DateTimeField(create_now=True)
    new_field.set_attributes_from_name("touched_at")

    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor._alter_field(
            DBDefaultsExample,
            old_field,
            new_field,
            old_type=_db_type(old_field),
            new_type=_db_type(new_field),
        )

    statements = [s.lower() for s in editor.executed_sql]
    set_idx = next(
        (
            i
            for i, s in enumerate(statements)
            if "set default statement_timestamp()" in s
        ),
        -1,
    )
    update_idx = next(
        (i for i, s in enumerate(statements) if "= default where" in s), -1
    )
    not_null_idx = next(
        (i for i, s in enumerate(statements) if "set not null" in s), -1
    )

    assert set_idx >= 0, "expected SET DEFAULT for the new expression"
    assert update_idx > set_idx, "UPDATE backfill must come after SET DEFAULT new"
    assert not_null_idx > update_idx, "SET NOT NULL must come after backfill"


def test_alter_field_drops_old_expression_default_before_type_change(db):
    """ALTER COLUMN TYPE with an incompatible expression DEFAULT in place
    will fail — Postgres can't cast e.g. STATEMENT_TIMESTAMP() to uuid.
    The schema editor must drop the old DEFAULT before the type alter.
    (SET DEFAULT for the NEW expression is reconciled by convergence.)"""
    from plain.postgres import fields as plain_fields

    connection = get_connection()

    old_field = plain_fields.DateTimeField(create_now=True)
    old_field.set_attributes_from_name("touched_at")
    new_field = plain_fields.UUIDField(generate=True)
    new_field.set_attributes_from_name("touched_at")

    with connection.schema_editor(atomic=False, collect_sql=True) as editor:
        editor._alter_field(
            DBDefaultsExample,
            old_field,
            new_field,
            old_type=_db_type(old_field),
            new_type=_db_type(new_field),
        )

    statements = [s.lower() for s in editor.executed_sql]
    drop_idx = next((i for i, s in enumerate(statements) if "drop default" in s), -1)
    type_idx = next((i for i, s in enumerate(statements) if "type uuid" in s), -1)

    assert drop_idx >= 0, "expected DROP DEFAULT before type change"
    assert type_idx > drop_idx, "type change must come after DROP DEFAULT"


def test_modelfield_to_formfield_excludes_expression_defaults():
    """Auto-generated form fields for DB-expression defaults must not carry
    the expression instance as `initial` (it's a Func object, not a UUID/
    datetime), and must not be `required` so the user can omit them and let
    the DB fill the value on INSERT."""
    from plain.postgres.forms import modelfield_to_formfield

    db_uuid_field = DBDefaultsExample._model_meta.get_forward_field("db_uuid")
    form_field = modelfield_to_formfield(db_uuid_field)
    assert form_field is not None
    assert form_field.initial is None
    assert form_field.required is False

    # And it doesn't break the usual path for static defaults.
    status_field = DefaultsExample._model_meta.get_forward_field("status")
    form_field = modelfield_to_formfield(status_field)
    assert form_field is not None
    assert form_field.initial == "pending"


def test_model_to_dict_omits_database_default_fields(db):
    """model_to_dict is commonly used to seed a Form's `initial` from an
    instance. If a DATABASE_DEFAULT sentinel leaked into that dict, it
    would override the formfield's own initial=None and render the
    repr `<DatabaseDefault>` in the rendered field."""
    from plain.postgres.forms import model_to_dict

    inst = DBDefaultsExample(name="x")
    as_dict = model_to_dict(inst)

    assert "name" in as_dict
    assert as_dict["name"] == "x"
    assert "db_uuid" not in as_dict
    assert "created_at" not in as_dict


def test_construct_instance_preserves_db_default_on_blank_submission(db):
    """A blank HTML input for a DDE-defaulted field comes through as an
    entry in form.data with a cleaned value of None/empty. construct_instance
    must not overwrite DATABASE_DEFAULT with None in that case — the whole
    point is to let Postgres evaluate the DEFAULT on INSERT."""
    from plain.postgres.forms import construct_instance

    # Minimal stand-in: construct_instance only reads `cleaned_data`, `data`,
    # `files`, and `form[name].field.empty_values` + `add_prefix`.
    class _FormField:
        empty_values = [None, "", [], (), {}]

    class _Bound:
        field = _FormField()

    class _Form:
        cleaned_data = {"name": "from-form", "db_uuid": None, "created_at": None}
        data = {"name": "from-form", "db_uuid": "", "created_at": ""}
        files: dict = {}

        def add_prefix(self, name: str) -> str:
            return name

        def __getitem__(self, name: str) -> _Bound:
            return _Bound()

    instance = DBDefaultsExample()
    assert instance.db_uuid is DATABASE_DEFAULT

    construct_instance(_Form(), instance)  # ty: ignore[invalid-argument-type]

    # Blank submission must NOT overwrite the sentinel with None.
    assert instance.db_uuid is DATABASE_DEFAULT
    assert instance.created_at is DATABASE_DEFAULT
    assert instance.name == "from-form"


def test_database_default_singleton_survives_pickling(db):
    """`Model().save()` after `pickle.dumps`/`loads` round-trip must still
    work — the sentinel identity check (`is DATABASE_DEFAULT`) drives both
    the descriptor and the INSERT compiler."""
    import pickle

    inst = DBDefaultsExample(name="pickle-me")
    assert inst.db_uuid is DATABASE_DEFAULT

    restored = pickle.loads(pickle.dumps(inst))
    assert restored.db_uuid is DATABASE_DEFAULT

    restored.save()
    assert isinstance(restored.db_uuid, uuid.UUID)


def test_save_with_explicit_pk_refreshes_db_default_fields_after_update(db):
    """When save() takes the UPDATE path against an existing row, fields
    that hold the DATABASE_DEFAULT sentinel must be refreshed from the DB
    so the in-memory instance doesn't keep the sentinel."""
    # First, create a row so the explicit-PK save below hits an UPDATE.
    original = DBDefaultsExample(name="original")
    original.save()

    # New unsaved instance with the SAME id and no value for db_uuid.
    # Skip clean_and_validate so the UPDATE-then-INSERT fallback path runs;
    # validate_unique would otherwise reject the colliding id.
    same_id = DBDefaultsExample(id=original.id, name="updated")
    assert same_id.db_uuid is DATABASE_DEFAULT

    same_id.save(clean_and_validate=False)

    # The UPDATE succeeded; db_uuid should now hold the DB's value, not
    # the sentinel.
    assert same_id.db_uuid is not DATABASE_DEFAULT
    assert same_id.db_uuid == original.db_uuid
    assert isinstance(same_id.db_uuid, uuid.UUID)


def test_save_with_explicit_pk_falls_back_to_insert(db):
    """When id is set but the row doesn't exist, save() tries UPDATE first
    then INSERT. The DATABASE_DEFAULT sentinel must not leak into the UPDATE
    path — only the INSERT can meaningfully evaluate a DB default."""
    inst = DBDefaultsExample(id=999_999, name="explicit-pk")
    inst.save()

    assert inst.id == 999_999
    assert isinstance(inst.db_uuid, uuid.UUID)
    assert isinstance(inst.created_at, datetime.datetime)

    reloaded = DBDefaultsExample.query.get(id=999_999)
    assert reloaded.db_uuid == inst.db_uuid


def test_datetime_update_now_requires_backfill_companion():
    """update_now=True has no DB DEFAULT of its own, so adding the column to
    an existing table has no way to populate rows unless the user also
    declares create_now=True (DB fills on INSERT) or allow_null=True."""
    from plain.postgres import fields as plain_fields

    bare = plain_fields.DateTimeField(update_now=True)
    bare.set_attributes_from_name("touched_at")
    bare_ids = {r.id for r in bare.preflight()}
    assert "fields.datetime_update_now_requires_backfill" in bare_ids

    with_create = plain_fields.DateTimeField(create_now=True, update_now=True)
    with_create.set_attributes_from_name("touched_at")
    assert with_create.preflight() == []

    with_null = plain_fields.DateTimeField(update_now=True, allow_null=True)
    with_null.set_attributes_from_name("touched_at")
    assert with_null.preflight() == []


def test_uuid_default_kwarg_rejected_at_signature():
    """UUIDField no longer accepts `default=` — Python-side UUID generation
    isn't supported; use `generate=True` or set the value explicitly."""
    from plain.postgres import fields as plain_fields

    with pytest.raises(TypeError, match="unexpected keyword argument 'default'"):
        plain_fields.UUIDField(default=uuid.uuid4)  # ty: ignore[unknown-argument]


def test_datetime_default_kwarg_rejected_at_signature():
    """DateTimeField no longer accepts `default=` — use `create_now=True` or
    `update_now=True`, or set the value explicitly."""
    from plain.postgres import fields as plain_fields

    with pytest.raises(TypeError, match="unexpected keyword argument 'default'"):
        plain_fields.DateTimeField(default=datetime.datetime(2020, 1, 1))  # ty: ignore[unknown-argument]


def test_get_db_default_expression_returns_now_when_create_now():
    from plain.postgres import fields as plain_fields

    field = plain_fields.DateTimeField(create_now=True)
    expr = field.get_db_default_expression()
    assert isinstance(expr, Now)


def test_get_db_default_expression_returns_gen_random_uuid_when_generate():
    from plain.postgres import fields as plain_fields

    field = plain_fields.UUIDField(generate=True)
    expr = field.get_db_default_expression()
    assert isinstance(expr, GenRandomUUID)


def test_get_db_default_expression_returns_none_by_default():
    from plain.postgres import fields as plain_fields

    assert plain_fields.DateTimeField().get_db_default_expression() is None
    assert plain_fields.UUIDField().get_db_default_expression() is None
    assert plain_fields.TextField().get_db_default_expression() is None
