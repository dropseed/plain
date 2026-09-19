"""QuerySet.returning() captures the rows touched by update() and delete().

Without returning(), update()/delete() return an int rowcount as always.
With it, no-arg returning() hydrates full model instances and
returning(*Model.field) returns a list of dicts holding just those columns.
"""

from __future__ import annotations

import pytest
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.returning import ReturningEvent
from plain.postgres import ReturningQuerySet
from plain.postgres.exceptions import FieldError


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
        ReturningEvent.query.filter(label="a")
        .returning(ReturningEvent.id, ReturningEvent.count)
        .update(count=7)
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
    rows = (
        ReturningEvent.query.filter(label="a")
        .returning(ReturningEvent.id, ReturningEvent.payload)
        .delete()
    )

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
    rows = (
        ReturningEvent.query.filter(label="missing")
        .returning(ReturningEvent.id)
        .delete()
    )
    assert rows == []


# ===========================================================================
# Validation and typing
# ===========================================================================


def test_returning_returns_a_returning_queryset(db):
    assert isinstance(ReturningEvent.query.returning(), ReturningQuerySet)
    assert isinstance(
        ReturningEvent.query.returning(ReturningEvent.id), ReturningQuerySet
    )


def test_returning_string_arg_errors(db):
    with pytest.raises(TypeError, match="takes field references, not strings"):
        ReturningEvent.query.returning("count")  # ty: ignore[invalid-argument-type]


def test_returning_wrong_model_field_errors(db):
    with pytest.raises(FieldError, match="belongs to a different model"):
        ReturningEvent.query.returning(DeleteParent.name)


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

    rows = (
        DeleteParent.query.filter(id=parent.id)
        .returning(DeleteParent.id, DeleteParent.name)
        .delete()
    )

    # Only the parent row comes back, even though two children were cascaded.
    assert len(rows) == 1
    assert rows[0] == {"id": parent.id, "name": "p"}
    assert ChildCascade.query.count() == 0


# ===========================================================================
# Joins — the WHERE id IN (subquery) rewrite keeps RETURNING
# ===========================================================================


def test_update_returning_across_a_relation(db, capture_queries):
    keep = DeleteParent(name="keep").create()
    move = DeleteParent(name="move").create()
    ChildCascade(parent=move).create()
    ChildCascade(parent=move).create()
    ChildCascade(parent=keep).create()

    with capture_queries() as queries:
        rows = (
            ChildCascade.query.filter(parent__name="move")
            .returning(ChildCascade.id)
            .update(parent=keep)
        )

    # Filtering across the FK rewrites the UPDATE to `WHERE id IN (subquery)`;
    # RETURNING has to survive that rewrite, in one statement.
    assert len(queries) == 1
    assert "RETURNING" in queries[0]["sql"]
    assert len(rows) == 2
    assert ChildCascade.query.filter(parent=keep).count() == 3


def test_delete_returning_across_a_relation(db, capture_queries):
    parent = DeleteParent(name="doomed").create()
    ChildCascade(parent=parent).create()
    ChildCascade(parent=parent).create()

    with capture_queries() as queries:
        rows = ChildCascade.query.filter(parent__name="doomed").returning().delete()

    assert len(queries) == 1
    assert "RETURNING" in queries[0]["sql"]
    assert len(rows) == 2
    assert all(row.parent.id == parent.id for row in rows)


# ===========================================================================
# Foreign key columns
# ===========================================================================


def test_returning_relation_reference_errors(db):
    # Model.fk is the relation, not the column, so it has no spelling here --
    # say that instead of dumping the descriptor's repr.
    with pytest.raises(FieldError, match="it is a relation, not a column"):
        ChildCascade.query.returning(ChildCascade.parent)  # ty: ignore[invalid-argument-type]


def test_returning_instances_carry_foreign_keys(db):
    parent = DeleteParent(name="p").create()
    ChildCascade(parent=parent).create()

    rows = ChildCascade.query.returning().delete()

    assert len(rows) == 1
    assert rows[0].parent.id == parent.id


# ===========================================================================
# Writes that RETURNING doesn't apply to say so
# ===========================================================================


@pytest.mark.parametrize(
    "write",
    [
        lambda qs: qs.create(label="x", count=1),
        lambda qs: qs.bulk_create([ReturningEvent(label="x", count=1)]),
        lambda qs: qs.bulk_update(list(ReturningEvent.query), ["count"]),
        lambda qs: qs.get_or_create(label="x", count=1),
        lambda qs: qs.update_or_create(label="x", defaults={"count": 1}),
    ],
    ids=["create", "bulk_create", "bulk_update", "get_or_create", "update_or_create"],
)
def test_returning_rejects_other_writes(db, write):
    ReturningEvent(label="seed", count=1).create()
    with pytest.raises(
        TypeError, match="only applies to update\\(\\) and delete\\(\\)"
    ):
        write(ReturningEvent.query.returning())
