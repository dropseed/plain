"""Explicit create() (INSERT) and update() (UPDATE) instance methods.

create() always inserts a new row; update() always updates an existing one.
Each refuses the wrong lifecycle state, and delete() resets the instance to
"new" so it can be create()'d again.
"""

from __future__ import annotations

import psycopg
import pytest
from app.examples.models.constraints import ConstraintExample
from app.examples.models.defaults import DBDefaultsExample
from app.examples.models.querysets import DefaultQuerySetModel
from app.examples.models.relationships import Tag, Widget, WidgetTag

from plain.exceptions import ValidationError
from plain.postgres import transaction
from plain.postgres.exceptions import FieldError

# ===========================================================================
# create()
# ===========================================================================


def test_create_inserts_and_returns_self(db):
    obj = DefaultQuerySetModel(name="x")
    result = obj.create()

    assert result is obj
    assert obj.id is not None
    assert obj._state.adding is False
    assert DefaultQuerySetModel.query.get(id=obj.id).name == "x"


def test_create_one_liner(db):
    obj = DefaultQuerySetModel(name="x").create()
    assert obj.id is not None


def test_create_on_persisted_instance_raises(db):
    obj = DefaultQuerySetModel(name="x").create()
    with pytest.raises(ValueError, match="already persisted"):
        obj.create()


def test_create_with_hand_set_id_inserts(db):
    # A hand-set id is inserted as given -- create() always INSERTs, so it is
    # itself the explicit "insert this id" action.
    obj = DefaultQuerySetModel(name="x")
    obj.id = 990_001
    obj.create()

    assert obj.id == 990_001
    assert DefaultQuerySetModel.query.get(id=990_001).name == "x"


def test_create_with_colliding_hand_set_id_raises(db):
    # A colliding id is rejected by the database (duplicate primary key). The
    # implicit PK isn't a declared constraint, so it surfaces raw, not mapped.
    existing = DefaultQuerySetModel(name="existing").create()
    clash = DefaultQuerySetModel(name="clash")
    clash.id = existing.id

    with pytest.raises(psycopg.IntegrityError):
        with transaction.atomic():
            clash.create()

    assert DefaultQuerySetModel.query.get(id=existing.id).name == "existing"


def test_create_maps_constraint_violation_to_validation_error(db):
    # A declared UniqueConstraint violation maps to ValidationError, same as a
    # pre-check would raise.
    ConstraintExample(name="dup", description="same").create()

    with pytest.raises(ValidationError):
        with transaction.atomic():
            ConstraintExample(name="dup", description="same").create()


def test_create_skips_validation_when_asked(db):
    # clean_and_validate=False still inserts.
    obj = DefaultQuerySetModel(name="x").create(clean_and_validate=False)
    assert obj.id is not None


# ===========================================================================
# update()
# ===========================================================================


def test_update_writes_and_returns_self(db):
    obj = DefaultQuerySetModel(name="x").create()
    obj.name = "y"
    result = obj.update()

    assert result is obj
    assert DefaultQuerySetModel.query.get(id=obj.id).name == "y"


def test_update_on_new_instance_raises(db):
    obj = DefaultQuerySetModel(name="x")
    with pytest.raises(ValueError, match="hasn't been created"):
        obj.update()


def test_update_fields_writes_only_named(db):
    obj = ConstraintExample(name="n1", description="d1").create()
    obj.name = "n2"
    obj.description = "d2"
    obj.update(fields=["name"])

    refreshed = ConstraintExample.query.get(id=obj.id)
    assert refreshed.name == "n2"
    assert refreshed.description == "d1"  # not in update_fields -- left alone


def test_update_fields_unknown_field_raises(db):
    obj = DefaultQuerySetModel(name="x").create()
    with pytest.raises(ValueError, match="do not exist"):
        obj.update(fields=["nope"])


def test_update_empty_update_fields_is_noop(db):
    obj = ConstraintExample(name="n1", description="d1").create()
    obj.name = "n2"
    obj.update(fields=[])

    assert ConstraintExample.query.get(id=obj.id).name == "n1"  # nothing written


def test_update_deferred_field_auto_excluded(db):
    obj = ConstraintExample(name="n1", description="d1").create()
    loaded = ConstraintExample.query.only("name").get(id=obj.id)
    loaded.name = "n2"
    loaded.update()  # update_fields auto-detected as the loaded fields only

    refreshed = ConstraintExample.query.get(id=obj.id)
    assert refreshed.name == "n2"
    assert refreshed.description == "d1"  # deferred -- never written


def test_update_explicit_deferred_field_raises(db):
    obj = ConstraintExample(name="n1", description="d1").create()
    loaded = ConstraintExample.query.only("name").get(id=obj.id)
    with pytest.raises(FieldError, match="deferred"):
        loaded.update(fields=["description"])


def test_update_no_matching_row_raises(db):
    # The row is deleted out from under a persisted instance -- update() has no
    # INSERT fallback, so it raises rather than silently vanishing.
    obj = ConstraintExample(name="n", description="d").create()
    ConstraintExample.query.filter(id=obj.id).delete()
    obj.name = "changed"

    with pytest.raises(psycopg.DatabaseError, match="affected no rows"):
        with transaction.atomic():
            obj.update()


# ===========================================================================
# unsaved-FK write guard
# ===========================================================================


def test_create_with_unsaved_foreign_key_raises(db):
    # Assigning an unsaved related object and writing it would silently lose the
    # FK -- create() refuses (the guard checks every concrete field).
    tag = Tag(name="t").create()
    wt = WidgetTag(widget=Widget(name="unsaved", size="m"), tag=tag)
    with pytest.raises(ValueError, match="unsaved related object"):
        wt.create()


def test_update_guards_only_the_fields_being_written(db):
    # The guard runs for the FK update() is about to write and skips the rest --
    # exercising the field-name filtering in _prepare_related_fields_for_save.
    widget = Widget(name="w", size="m").create()
    tag = Tag(name="t").create()
    wt = WidgetTag(widget=widget, tag=tag).create()

    # Reassign an unsaved widget in memory.
    wt.widget = Widget(name="unsaved", size="m")

    # Writing the widget column hits the guard (and raises before any SQL).
    with pytest.raises(ValueError, match="unsaved related object"):
        wt.update(fields=["widget"])

    # Writing only the tag column skips the unsaved widget -- it's not in the
    # written set, so the guard doesn't fire. (clean_and_validate=False isolates
    # the guard from the whole-instance shape check, which flags the null widget
    # on its own.)
    wt.update(fields=["tag"], clean_and_validate=False)  # does not raise


# ===========================================================================
# delete() lifecycle
# ===========================================================================


def test_delete_resets_adding_so_create_reinserts(db):
    obj = DefaultQuerySetModel(name="x").create()
    obj.delete()

    assert obj._state.adding is True
    assert obj.id is None

    obj.create()  # re-inserts cleanly under a fresh id
    assert obj.id is not None
    assert DefaultQuerySetModel.query.get(id=obj.id).name == "x"


def test_update_after_delete_raises(db):
    obj = DefaultQuerySetModel(name="x").create()
    obj.delete()
    with pytest.raises(ValueError, match="hasn't been created"):
        obj.update()


def test_delete_preserves_field_values_except_id(db):
    # delete() clears only the id -- every other field survives so callers can
    # still reference the deleted row (correlate it, log it, filter to confirm
    # it's gone). Server-default fields keep their populated values too.
    obj = DBDefaultsExample(name="x").create()
    uuid_before, created_before, token_before = (
        obj.db_uuid,
        obj.created_at,
        obj.token,
    )

    obj.delete()

    assert obj.id is None
    assert obj.name == "x"
    assert obj.db_uuid == uuid_before  # readable after delete, not a sentinel
    assert obj.created_at == created_before
    assert obj.token == token_before
    # And the row really is gone -- filtering by the preserved uuid finds nothing.
    assert not DBDefaultsExample.query.filter(db_uuid=obj.db_uuid).exists()


def test_lifecycle_guard_does_not_poison_transaction(db):
    """create()/update()'s lifecycle guards raise before any SQL (above the
    rollback-marking write block), so catching one inside an open atomic()
    leaves the transaction usable."""
    with transaction.atomic():
        persisted = DefaultQuerySetModel(name="x").create()
        with pytest.raises(ValueError, match="already persisted"):
            persisted.create()  # guard raises before touching the database

        # The transaction wasn't marked for rollback -- this still commits.
        survivor = DefaultQuerySetModel.query.create(name="survivor")

    assert DefaultQuerySetModel.query.get(id=survivor.id).name == "survivor"
