"""
Delete / on_delete behavior tests.

Sections:
    1. on_delete options — instance + queryset paths for each action
    2. Graph shapes — multi-level, diamond, self-ref, M2M, mixed, circular
    3. Deferred FK / transaction semantics
    4. Return value shape
    5. QuerySet operator rejections / leniency
    6. Related manager + M2M through-table mutation
    7. Idempotency
    8. Query-count canary
    9. Collector-specific behavior — deleted wholesale when the DB-level
       ON DELETE rewrite lands (PROTECT, SET(callable), db_constraint=False
       app-level cascade). See
       Futures/plain/postgres-native/models-db-level-on-delete.md.
"""

from __future__ import annotations

import psycopg
import pytest
from app.examples.models import (
    Car,
    CarFeature,
    ChildCascade,
    ChildNoAction,
    ChildProtect,
    ChildRestrict,
    ChildSetCallable,
    ChildSetNull,
    CircA,
    CircB,
    DeleteParent,
    DiamondChild,
    DiamondParentA,
    DiamondParentB,
    Feature,
    Grandchild,
    Grandparent,
    MidParent,
    SetSentinelParent,
    TreeNode,
    UnconstrainedChild,
)

from plain.postgres import transaction
from plain.postgres.deletion import ProtectedError, RestrictedError


def _create_parents():
    default_parent = DeleteParent.query.create(name="default")
    parent = DeleteParent.query.create(name="parent")
    return default_parent, parent


# ===========================================================================
# 1. on_delete options — instance.delete() and QuerySet.delete() per option
# ===========================================================================


def test_cascade_instance(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildCascade.query.create(parent=parent)
    parent.delete()
    assert ChildCascade.query.count() == 0


def test_cascade_queryset(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    for _ in range(3):
        ChildCascade.query.create(parent=parent)

    DeleteParent.query.filter(id=parent.id).delete()

    assert ChildCascade.query.count() == 0
    assert not DeleteParent.query.filter(id=parent.id).exists()


def test_restrict_instance(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildRestrict.query.create(parent=parent)
    with pytest.raises(RestrictedError):
        parent.delete()
    assert DeleteParent.query.filter(id=parent.id).exists()


def test_restrict_queryset(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildRestrict.query.create(parent=parent)

    with pytest.raises(RestrictedError):
        DeleteParent.query.filter(id=parent.id).delete()

    assert DeleteParent.query.filter(id=parent.id).exists()


def test_set_null_instance(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child = ChildSetNull.query.create(parent=parent)
    parent.delete()
    child.refresh_from_db()
    assert child.parent_id is None


def test_set_null_queryset(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child_ids = [ChildSetNull.query.create(parent=parent).id for _ in range(3)]

    DeleteParent.query.filter(id=parent.id).delete()

    for cid in child_ids:
        assert ChildSetNull.query.get(id=cid).parent_id is None


def test_set_null_bulk(db):
    """Parent with many children — all end up null in one shot."""
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child_ids = [ChildSetNull.query.create(parent=parent).id for _ in range(100)]

    parent.delete()

    nulls = ChildSetNull.query.filter(id__in=child_ids, parent_id__isnull=True).count()
    assert nulls == 100


def test_no_action_raises_at_commit(db):
    """
    NO_ACTION skips application-level FK handling; the DB's deferred
    constraint check fires at commit. The pytest fixture wraps tests in a
    never-committed atomic, so force the check with SET CONSTRAINTS ALL
    IMMEDIATE inside a savepoint.
    """
    from plain.postgres.db import get_connection

    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildNoAction.query.create(parent=parent)

    with pytest.raises(psycopg.IntegrityError):  # noqa: PT012
        with transaction.atomic():
            parent.delete()
            with get_connection().cursor() as cur:
                cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_filtered_delete_only_cascades_filtered(db):
    """`.filter(...).delete()` must not touch rows outside the filter."""
    default_parent, parent = _create_parents()
    other = DeleteParent.query.create(name="other")

    keeper = ChildCascade.query.create(parent=other)
    ChildCascade.query.create(parent=parent)

    DeleteParent.query.filter(id=parent.id).delete()

    assert ChildCascade.query.filter(id=keeper.id).exists()
    assert ChildCascade.query.count() == 1
    assert DeleteParent.query.filter(id=other.id).exists()


# ===========================================================================
# 2. Graph shapes
# ===========================================================================


def test_three_level_cascade(db):
    gp = Grandparent.query.create(name="gp")
    mid = MidParent.query.create(grandparent=gp)
    grandchild_id = Grandchild.query.create(mid_parent=mid).id

    gp.delete()

    assert not MidParent.query.filter(id=mid.id).exists()
    assert not Grandchild.query.filter(id=grandchild_id).exists()


def test_diamond_shared_child_deleted_once(db):
    a = DiamondParentA.query.create(name="a")
    b = DiamondParentB.query.create(name="b")
    child_id = DiamondChild.query.create(parent_a=a, parent_b=b).id

    a.delete()

    assert not DiamondChild.query.filter(id=child_id).exists()
    # b survives; its reference to the child is already gone
    assert DiamondParentB.query.filter(id=b.id).exists()


def test_self_referential_tree_cascade(db):
    root = TreeNode(name="root", parent=None)
    root.save(clean_and_validate=False)
    mid = TreeNode.query.create(name="mid", parent=root)
    leaf = TreeNode.query.create(name="leaf", parent=mid)

    root.delete()

    assert TreeNode.query.count() == 0
    assert not TreeNode.query.filter(id=leaf.id).exists()


def test_m2m_through_cascades_from_either_side(db):
    """
    `car.delete()` or `feat.delete()` both cascade the through-row, leaving
    the other side intact.
    """
    car = Car.query.create(make="Ford", model="F150")
    feat = Feature.query.create(name="4wd")
    CarFeature.query.create(car=car, feature=feat)

    car.delete()
    assert CarFeature.query.count() == 0
    assert Feature.query.filter(id=feat.id).exists()

    # Symmetric: delete from the other side
    car2 = Car.query.create(make="Ford", model="F250")
    CarFeature.query.create(car=car2, feature=feat)

    feat.delete()
    assert CarFeature.query.count() == 0
    assert Car.query.filter(id=car2.id).exists()


def test_mixed_on_delete_restrict_blocks_cascade(db):
    """
    Parent has both CASCADE and RESTRICT children. RESTRICT must abort the
    whole delete — the CASCADE child must NOT be deleted either.
    """
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    cascade_child = ChildCascade.query.create(parent=parent)
    restrict_child = ChildRestrict.query.create(parent=parent)

    with pytest.raises(RestrictedError):
        parent.delete()

    assert DeleteParent.query.filter(id=parent.id).exists()
    assert ChildCascade.query.filter(id=cascade_child.id).exists()
    assert ChildRestrict.query.filter(id=restrict_child.id).exists()


def test_circular_fk_cascade_inside_atomic(db):
    """
    A.partner → B, B.partner → A, both CASCADE. Plain's FK constraints are
    DEFERRABLE INITIALLY DEFERRED, so deleting either side inside one atomic
    should cascade to the other and commit cleanly. If the rewrite switches
    constraints to IMMEDIATE, this test catches it.
    """
    with transaction.atomic():
        a = CircA.query.create(name="a")
        b = CircB.query.create(name="b", partner=a)
        a.partner = b
        a.save()

    with transaction.atomic():
        a.delete()

    assert not CircA.query.filter(id=a.id).exists()
    assert not CircB.query.filter(id=b.id).exists()


# ===========================================================================
# 3. Deferred FK / transaction semantics
# ===========================================================================


def test_delete_and_reinsert_replacement_in_one_atomic(db):
    """
    FK is DEFERRABLE INITIALLY DEFERRED. Delete a parent and re-point a child
    at a replacement inside one atomic — commit must succeed.
    """
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child = ChildSetNull.query.create(parent=parent)

    with transaction.atomic():
        replacement = DeleteParent.query.create(name="replacement")
        child.parent = replacement
        child.save()
        parent.delete()

    child.refresh_from_db()
    assert child.parent_id == DeleteParent.query.get(name="replacement").id


def test_child_insert_before_parent_in_one_atomic(db):
    """
    Insert a child pointing at a not-yet-existing parent id, then insert the
    parent. Deferred FK means the constraint is only checked at commit, by
    which point the parent exists.
    """
    from plain.postgres.db import get_connection

    with transaction.atomic():
        with get_connection().cursor() as cur:
            cur.execute(
                "SELECT nextval(pg_get_serial_sequence('examples_deleteparent', 'id'))"
            )
            row = cur.fetchone()
            assert row is not None
            (new_id,) = row

        child = ChildCascade(parent_id=new_id)
        child.save(clean_and_validate=False)

        parent = DeleteParent(id=new_id, name="late")
        parent.save(clean_and_validate=False)

    assert DeleteParent.query.filter(id=new_id).exists()
    assert ChildCascade.query.filter(parent_id=new_id).exists()


# ===========================================================================
# 4. Return value shape — (count, {label: count})
# ===========================================================================


def test_instance_delete_return_value(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildCascade.query.create(parent=parent)
    ChildCascade.query.create(parent=parent)

    count, by_label = parent.delete()

    assert count == 3  # 1 parent + 2 children
    assert by_label == {
        DeleteParent.model_options.label: 1,
        ChildCascade.model_options.label: 2,
    }


def test_queryset_delete_return_value(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildCascade.query.create(parent=parent)

    count, by_label = DeleteParent.query.filter(id=parent.id).delete()

    assert count == 2
    assert by_label[DeleteParent.model_options.label] == 1
    assert by_label[ChildCascade.model_options.label] == 1


def test_queryset_delete_empty_returns_zero(db):
    count, by_label = DeleteParent.query.filter(name="nonexistent").delete()
    assert count == 0
    assert by_label == {}


# ===========================================================================
# 5. QuerySet operator rejections / leniency
# ===========================================================================


def test_delete_rejects_sliced_queryset(db):
    _create_parents()
    qs = DeleteParent.query.all()[:1]
    with pytest.raises(TypeError):
        qs.delete()  # ty: ignore[unresolved-attribute]


def test_delete_rejects_distinct_queryset(db):
    _create_parents()
    with pytest.raises(TypeError):
        DeleteParent.query.distinct().delete()


def test_delete_rejects_values_queryset(db):
    _create_parents()
    with pytest.raises(TypeError):
        DeleteParent.query.values("name").delete()


def test_order_by_is_silently_stripped_not_rejected(db):
    """
    `.order_by().delete()` is accepted — the order is irrelevant to the
    result. Pin this so a stricter rewrite doesn't start rejecting it.
    """
    _create_parents()
    count, _ = DeleteParent.query.order_by("name").delete()
    assert count == 2


# ===========================================================================
# 6. Related manager + M2M through-table mutation
# ===========================================================================


def test_related_manager_delete(db):
    """
    `parent.childcascade_set.query.delete()` is a distinct code path from
    `ChildCascade.query.filter(parent=parent).delete()`.
    """
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    other = DeleteParent.query.create(name="other")

    ChildCascade.query.create(parent=parent)
    ChildCascade.query.create(parent=parent)
    keeper = ChildCascade.query.create(parent=other)

    parent.childcascade_set.query.delete()

    assert ChildCascade.query.filter(parent=parent).count() == 0
    assert ChildCascade.query.filter(id=keeper.id).exists()
    assert DeleteParent.query.filter(id=parent.id).exists()


def test_m2m_remove_deletes_through_row(db):
    car = Car.query.create(make="Ford", model="F150")
    feat_a = Feature.query.create(name="4wd")
    feat_b = Feature.query.create(name="towing")
    car.features.add(feat_a, feat_b)

    car.features.remove(feat_a)

    assert CarFeature.query.filter(car=car).count() == 1
    assert CarFeature.query.filter(car=car, feature=feat_b).exists()
    assert Feature.query.filter(id=feat_a.id).exists()


def test_m2m_clear_deletes_all_through_rows(db):
    car = Car.query.create(make="Ford", model="F150")
    feat_a = Feature.query.create(name="4wd")
    feat_b = Feature.query.create(name="towing")
    car.features.add(feat_a, feat_b)

    car.features.clear()

    assert CarFeature.query.filter(car=car).count() == 0
    assert Feature.query.count() == 2


def test_m2m_set_reconciles_through_rows(db):
    car = Car.query.create(make="Ford", model="F150")
    a = Feature.query.create(name="a")
    b = Feature.query.create(name="b")
    c = Feature.query.create(name="c")
    car.features.add(a, b)

    car.features.set([b, c])

    feat_ids = set(
        CarFeature.query.filter(car=car).values_list("feature_id", flat=True)
    )
    assert feat_ids == {b.id, c.id}


# ===========================================================================
# 7. Idempotency
# ===========================================================================


def test_delete_already_deleted_instance_raises(db):
    """
    After `.delete()`, Plain sets `instance.id = None`. A second `.delete()`
    raises ValueError. Pin this — users who expect a second delete to be a
    no-op are in for a surprise today.
    """
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    parent.delete()

    with pytest.raises(ValueError, match="id attribute is set to None"):
        parent.delete()


# ===========================================================================
# 8. Query-count canary
# ===========================================================================


def test_cascade_query_count_canary(db):
    """
    Pins the number of queries issued for a single-level CASCADE delete.

    Today's Collector issues multiple queries (SELECT children, DELETE
    children, DELETE parent). Under DB-level ON DELETE CASCADE this should
    drop to ~1-2. When this test fails post-rewrite, update the expected
    count to lock in the gain.
    """
    from plain.postgres.db import get_connection

    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    for _ in range(5):
        ChildCascade.query.create(parent=parent)

    conn = get_connection()
    prev_force = conn.force_debug_cursor
    conn.force_debug_cursor = True
    conn.queries_log.clear()
    try:
        parent.delete()
        query_count = len(conn.queries_log)
    finally:
        conn.force_debug_cursor = prev_force

    # Today: Collector issues multiple queries.
    # Post-rewrite: should be 1 DELETE (Postgres handles the cascade).
    assert query_count > 1, (
        f"Collector should issue multiple queries today; got {query_count}"
    )


# ===========================================================================
# 9. Collector-specific behavior — delete wholesale during the rewrite
# ===========================================================================


def test_protect_instance(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildProtect.query.create(parent=parent)
    with pytest.raises(ProtectedError):
        parent.delete()
    assert DeleteParent.query.filter(id=parent.id).exists()


def test_protect_queryset(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildProtect.query.create(parent=parent)

    with pytest.raises(ProtectedError):
        DeleteParent.query.filter(id=parent.id).delete()

    assert DeleteParent.query.filter(id=parent.id).exists()


def test_protect_fires_in_python_before_delete(db):
    """PROTECT fires in-Python before DELETE is issued — not at commit."""
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildProtect.query.create(parent=parent)

    with pytest.raises(ProtectedError):
        with transaction.atomic():
            parent.delete()


def test_protect_error_carries_referenced_objects(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child = ChildProtect.query.create(parent=parent)

    with pytest.raises(ProtectedError) as excinfo:
        parent.delete()

    assert child in list(excinfo.value.protected_objects)


def test_protect_error_message_mentions_model(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildProtect.query.create(parent=parent)

    with pytest.raises(ProtectedError) as excinfo:
        parent.delete()

    msg = str(excinfo.value)
    assert "ChildProtect" in msg or "childprotect" in msg.lower()


def test_restrict_error_carries_referenced_objects(db):
    """`RestrictedError.restricted_objects` is populated by the Collector;
    under DB-level RESTRICT this becomes a plain `IntegrityError`."""
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child = ChildRestrict.query.create(parent=parent)

    with pytest.raises(RestrictedError) as excinfo:
        parent.delete()

    assert child in list(excinfo.value.restricted_objects)


def test_set_callable_reassigns_to_sentinel(db):
    """SET(callable) — Collector-only feature; no DB mapping."""
    SetSentinelParent.query.create(name="sentinel")
    doomed = SetSentinelParent.query.create(name="doomed")
    sentinel = SetSentinelParent.query.get(name="sentinel")

    child = ChildSetCallable.query.create(parent=doomed)
    doomed.delete()

    child.refresh_from_db()
    assert child.parent_id == sentinel.id


def test_unconstrained_fk_still_cascades_via_collector(db):
    """
    FK with db_constraint=False has no DB-level constraint, but the Collector
    still honors on_delete=CASCADE. Under DB-level, the rewrite must decide
    whether this combo is rejected at model-check time or silently no-ops.
    """
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child_id = UnconstrainedChild.query.create(parent=parent).id

    parent.delete()

    assert not UnconstrainedChild.query.filter(id=child_id).exists()
