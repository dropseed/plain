"""The auto-generated primary key can't be passed to the constructor.

Postgres owns the identity `id`. `Model(id=...)` (and `query.create(id=...)`)
is rejected -- it almost always means "load the row with this id," which is a
query (`query.get(id=...)`), not construction. Assigning `obj.id = N` after
construction and calling `create()` IS allowed (the deliberate path for a
sequence-reserved id -- see test_create_update / test_delete_behaviors). Loading
real rows is exempt -- that path passes `_from_db=True`.
"""

from __future__ import annotations

import pytest
from app.examples.models.querysets import DefaultQuerySetModel


def test_constructing_with_id_raises():
    with pytest.raises(
        ValueError,
        match=r"Cannot set the auto-generated primary key 'id'.*query\.get",
    ):
        DefaultQuerySetModel(id=1, name="x")  # ty: ignore[unknown-argument]


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
    obj = DefaultQuerySetModel(id=None, name="x")  # ty: ignore[unknown-argument]
    assert obj.id is None


def test_loaded_rows_keep_their_id(db):
    # from_db() is exempt: real rows load with their id intact.
    created = DefaultQuerySetModel.query.create(name="loaded")
    fetched = DefaultQuerySetModel.query.get(id=created.id)
    assert fetched.id == created.id
