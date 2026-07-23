"""QuerySet.returning() captures the rows touched by update() and delete().

Without returning(), update()/delete() return an int rowcount as always.
With it, no-arg returning() hydrates full model instances and returning(*names)
returns a list of dicts holding just those columns.
"""

from __future__ import annotations

import pytest
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.returning import ReturningEvent

from plain.postgres.exceptions import FieldError
from plain.postgres.query import ReturningQuerySet


def _seed_events() -> None:
    ReturningEvent(label="a", count=1, payload={"n": 1}).create()
    ReturningEvent(label="a", count=1, payload={"n": 2}).create()
    ReturningEvent(label="b", count=1, payload=None).create()


# ===========================================================================
# update()
# ===========================================================================


def test_update_without_returning_returns_int(db):
    _seed_events()
    result = ReturningEvent.query.filter(label="a").update(count=5)
    assert result == 2


def test_update_returning_instances_reflect_new_values(db):
    _seed_events()
    rows = ReturningEvent.query.filter(label="a").returning().update(count=9)

    assert len(rows) == 2
    assert all(isinstance(row, ReturningEvent) for row in rows)
    # RETURNING on UPDATE reports the post-update values.
    assert {row.count for row in rows} == {9}
    # JSON converters are applied — payload comes back as a dict, not a string.
    payloads = [row.payload for row in rows]
    assert {p["n"] for p in payloads if p} == {1, 2}


def test_update_returning_named_fields_are_dicts(db):
    _seed_events()
    rows = (
        ReturningEvent.query.filter(label="a").returning("id", "count").update(count=7)
    )

    assert len(rows) == 2
    assert all(isinstance(row, dict) for row in rows)
    assert all(set(row) == {"id", "count"} for row in rows)
    assert {row["count"] for row in rows} == {7}


def test_update_returning_empty_result_is_empty_list(db):
    _seed_events()
    rows = ReturningEvent.query.filter(label="missing").returning().update(count=1)
    assert rows == []


# ===========================================================================
# delete()
# ===========================================================================


def test_delete_without_returning_returns_int(db):
    _seed_events()
    result = ReturningEvent.query.filter(label="a").delete()
    assert result == 2


def test_delete_returning_named_fields_gives_deleted_rows(db):
    _seed_events()
    rows = ReturningEvent.query.filter(label="a").returning("id", "payload").delete()

    assert len(rows) == 2
    assert all(isinstance(row, dict) and set(row) == {"id", "payload"} for row in rows)
    # DELETE ... RETURNING reports the rows as they were.
    assert {tuple(row["payload"].items()) for row in rows} == {
        (("n", 1),),
        (("n", 2),),
    }
    assert not ReturningEvent.query.filter(label="a").exists()


def test_delete_returning_instances(db):
    _seed_events()
    rows = ReturningEvent.query.filter(label="b").returning().delete()

    assert len(rows) == 1
    assert isinstance(rows[0], ReturningEvent)
    assert rows[0].label == "b"


def test_delete_returning_empty_result_is_empty_list(db):
    rows = ReturningEvent.query.filter(label="missing").returning("id").delete()
    assert rows == []


# ===========================================================================
# Validation and typing
# ===========================================================================


def test_returning_returns_a_returning_queryset(db):
    assert isinstance(ReturningEvent.query.returning(), ReturningQuerySet)
    assert isinstance(ReturningEvent.query.returning("id"), ReturningQuerySet)


def test_returning_bad_field_name_errors(db):
    with pytest.raises(FieldError, match="no such field"):
        ReturningEvent.query.returning("not_a_field")


def test_returning_before_filter_is_preserved(db):
    _seed_events()
    rows = ReturningEvent.query.returning().filter(label="a").update(count=3)
    assert len(rows) == 2
    assert {row.count for row in rows} == {3}


def test_returning_then_values_update_errors(db):
    # .values() + returning() is nonsensical; it must not silently misbehave.
    with pytest.raises(TypeError, match="after .values"):
        ReturningEvent.query.returning().values("id").update(count=1)


# ===========================================================================
# FK cascade — RETURNING only reports the target table's rows
# ===========================================================================


def test_delete_returning_excludes_cascade_deleted_children(db):
    parent = DeleteParent(name="p").create()
    ChildCascade(parent=parent).create()
    ChildCascade(parent=parent).create()

    rows = DeleteParent.query.filter(id=parent.id).returning("id", "name").delete()

    # Only the parent row comes back, even though two children were cascaded.
    assert len(rows) == 1
    assert rows[0] == {"id": parent.id, "name": "p"}
    assert ChildCascade.query.count() == 0
