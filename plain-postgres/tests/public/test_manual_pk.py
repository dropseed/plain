"""The auto-generated primary key can't be set by hand.

Postgres owns the identity `id`. Constructing a model with an explicit `id`
is rejected outright (use query.get() to load an existing row), and so is
saving a new instance whose `id` was assigned after construction
(`obj.id = N`) -- that check sits in save_base, before any SQL, so a hand-set
id never reaches (or overwrites) the database. Loading real rows is exempt --
that path passes `_from_db=True`. The deliberate escape hatch, for a
sequence-reserved id you genuinely own, is `save(force_insert=True)`.
"""

from __future__ import annotations

import psycopg
import pytest
from app.examples.models.querysets import DefaultQuerySetModel

from plain.postgres import transaction


def test_constructing_with_id_raises():
    with pytest.raises(
        ValueError,
        match=r"Cannot set the auto-generated primary key 'id'.*query\.get",
    ):
        DefaultQuerySetModel(id=1, name="x")


def test_query_create_with_id_raises():
    # query.create() constructs the instance first, so it rejects a manual
    # id the same way (before any database work).
    with pytest.raises(ValueError, match=r"auto-generated primary key 'id'"):
        DefaultQuerySetModel.query.create(id=1, name="x")


def test_constructing_without_id_is_fine():
    obj = DefaultQuerySetModel(name="x")
    assert obj.id is None


def test_explicit_id_none_is_allowed():
    # id=None is the field's own default — not a manual assignment, so it's
    # allowed rather than treated as a collision risk.
    obj = DefaultQuerySetModel(id=None, name="x")
    assert obj.id is None


def test_loaded_rows_keep_their_id(db):
    # from_db() is exempt: real rows load with their id intact.
    created = DefaultQuerySetModel.query.create(name="loaded")
    fetched = DefaultQuerySetModel.query.get(id=created.id)
    assert fetched.id == created.id


def test_setattr_colliding_id_raises_not_overwrites(db):
    """Assigning `obj.id` after construction and saving a new instance raises
    before any SQL runs -- Postgres owns the auto `id`. A colliding id can't
    reach (let alone overwrite) the existing row."""
    existing = DefaultQuerySetModel.query.create(name="existing")

    clash = DefaultQuerySetModel(name="clash")
    clash.id = existing.id

    with pytest.raises(ValueError, match="hand-set primary key"):
        clash.save()

    assert DefaultQuerySetModel.query.get(id=existing.id).name == "existing"


def test_setattr_colliding_id_with_update_fields_raises(db):
    """update_fields on a new instance is rejected before any SQL -- a
    never-persisted instance has no row to UPDATE, even when an id was hand-set
    to collide with an existing row. The existing row is left intact."""
    existing = DefaultQuerySetModel.query.create(name="existing")

    clash = DefaultQuerySetModel(name="clash")
    clash.id = existing.id

    with pytest.raises(ValueError, match="no persisted row to update"):
        clash.save(update_fields=["name"])

    assert DefaultQuerySetModel.query.get(id=existing.id).name == "existing"


def test_hand_set_id_raise_does_not_poison_transaction(db):
    """The guard raises above save_base's rollback-marking block, so catching
    it inside an open transaction.atomic() leaves the transaction usable -- no
    SQL ran, so there's nothing to roll back."""
    with transaction.atomic():
        clash = DefaultQuerySetModel(name="clash")
        clash.id = 123_456
        with pytest.raises(ValueError, match="hand-set primary key"):
            clash.save()

        # The transaction is still usable: this write succeeds and commits.
        survivor = DefaultQuerySetModel.query.create(name="survivor")

    assert DefaultQuerySetModel.query.get(id=survivor.id).name == "survivor"


def test_setattr_id_with_force_insert_inserts(db):
    """The deliberate opt-in: a sequence-reserved (or otherwise owned) id is
    INSERTed by passing force_insert=True."""
    obj = DefaultQuerySetModel(name="explicit")
    obj.id = 555_001
    obj.save(force_insert=True)

    assert DefaultQuerySetModel.query.get(id=555_001).name == "explicit"


def test_force_insert_colliding_id_raises_not_overwrites(db):
    """force_insert with a colliding id is rejected by the database (duplicate
    primary key) as a raw IntegrityError -- the existing row is never
    overwritten. Unlike the pre-write ValueError, this one runs SQL, so it
    marks the transaction for rollback (hence the inner atomic())."""
    existing = DefaultQuerySetModel.query.create(name="existing")

    clash = DefaultQuerySetModel(name="clash")
    clash.id = existing.id

    with pytest.raises(psycopg.IntegrityError):
        with transaction.atomic():
            clash.save(force_insert=True)

    assert DefaultQuerySetModel.query.get(id=existing.id).name == "existing"
