"""The auto-generated primary key can't be set by hand.

Postgres owns the identity `id`, so constructing a model with an explicit
`id` is rejected: a hand-set, already-used id would otherwise reach
_save_table's UPDATE-first path on save() and silently overwrite that row.
Loading real rows from the database is exempt — that path passes
`_from_db=True`.
"""

from __future__ import annotations

import pytest
from app.examples.models.querysets import DefaultQuerySetModel


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
