"""
Delete / on_delete behavior tests.

Cascading is enforced entirely by Postgres. Model.delete() and
QuerySet.delete() issue a single DELETE statement; child rows are handled
via the declared `ON DELETE` clauses (CASCADE, SET_NULL, RESTRICT, NO_ACTION).

Sections:
    1. on_delete options — instance + queryset paths for each action
    2. Graph shapes — multi-level, diamond, self-ref, M2M, mixed, circular
    3. Deferred FK / transaction semantics
    4. Return value — delete() returns an int row count
    5. QuerySet operator rejections / leniency
    6. Related manager + M2M through-table mutation
    7. Idempotency
    8. Query-count canary
"""

from __future__ import annotations

import psycopg
import pytest
from app.examples.models.delete import (
    ChildCascade,
    ChildNoAction,
    ChildRestrict,
    ChildSetNull,
    CircA,
    CircB,
    DeleteParent,
    DiamondChild,
    DiamondParentA,
    DiamondParentB,
    Grandchild,
    Grandparent,
    HideableItem,
    MidParent,
    UnconstrainedChild,
)
from app.examples.models.relationships import Tag, Widget, WidgetTag
from app.examples.models.trees import TreeNode

from plain.postgres import transaction


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
    """RESTRICT is immediate — raises at the DELETE call site even inside
    a transaction, regardless of DEFERRABLE INITIALLY DEFERRED."""
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildRestrict.query.create(parent=parent)
    # Inner atomic so the failed DELETE rolls back to a savepoint, leaving the
    # outer pytest fixture transaction usable for follow-up assertions.
    with pytest.raises(psycopg.errors.IntegrityError):  # noqa: PT012
        with transaction.atomic():
            parent.delete()
    assert DeleteParent.query.filter(id=parent.id).exists()


def test_restrict_queryset(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildRestrict.query.create(parent=parent)

    with pytest.raises(psycopg.errors.IntegrityError):  # noqa: PT012
        with transaction.atomic():
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
    """Parent with many children — all end up null in one Postgres-driven pass."""
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child_ids = [ChildSetNull.query.create(parent=parent).id for _ in range(100)]

    parent.delete()

    nulls = ChildSetNull.query.filter(id__in=child_ids, parent_id__isnull=True).count()
    assert nulls == 100


def test_no_action_raises_at_commit(db):
    """
    NO_ACTION respects DEFERRABLE INITIALLY DEFERRED — orphan detection is
    deferred to commit. Force the check inside a savepoint so the outer
    transaction stays clean under pytest's never-committed atomic wrapper.
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
    `widget.delete()` or `tag.delete()` both cascade the through-row, leaving
    the other side intact.
    """
    widget = Widget.query.create(name="Ford", size="F150")
    tag = Tag.query.create(name="4wd")
    WidgetTag.query.create(widget=widget, tag=tag)

    widget.delete()
    assert WidgetTag.query.count() == 0
    assert Tag.query.filter(id=tag.id).exists()

    # Symmetric: delete from the other side
    widget2 = Widget.query.create(name="Ford", size="F250")
    WidgetTag.query.create(widget=widget2, tag=tag)

    tag.delete()
    assert WidgetTag.query.count() == 0
    assert Widget.query.filter(id=widget2.id).exists()


def test_mixed_on_delete_restrict_blocks_cascade(db):
    """
    Parent has both CASCADE and RESTRICT children. Postgres evaluates all
    FK actions before applying the DELETE — RESTRICT raises and the would-be
    CASCADE child is untouched.
    """
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    cascade_child = ChildCascade.query.create(parent=parent)
    restrict_child = ChildRestrict.query.create(parent=parent)

    with pytest.raises(psycopg.errors.IntegrityError):  # noqa: PT012
        with transaction.atomic():
            parent.delete()

    assert DeleteParent.query.filter(id=parent.id).exists()
    assert ChildCascade.query.filter(id=cascade_child.id).exists()
    assert ChildRestrict.query.filter(id=restrict_child.id).exists()


def test_circular_fk_cascade_inside_atomic(db):
    """
    A.partner → B, B.partner → A, both CASCADE. Plain's FK constraints are
    DEFERRABLE INITIALLY DEFERRED, so deleting either side inside one atomic
    should cascade to the other and commit cleanly.
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
# 4. Return value — delete() returns an int
# ===========================================================================


def test_instance_delete_returns_one(db):
    """instance.delete() returns 1 for a successful delete.

    Cascaded child rows are handled by Postgres and are not counted.
    """
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildCascade.query.create(parent=parent)
    ChildCascade.query.create(parent=parent)

    assert parent.delete() == 1
    # But children were still cascaded at the DB level
    assert ChildCascade.query.count() == 0


def test_queryset_delete_returns_count(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildCascade.query.create(parent=parent)

    count = DeleteParent.query.filter(id=parent.id).delete()

    assert count == 1  # one parent row; children cascaded by Postgres
    assert ChildCascade.query.count() == 0


def test_queryset_delete_empty_returns_zero(db):
    count = DeleteParent.query.filter(name="nonexistent").delete()
    assert count == 0


def test_queryset_delete_multi_row(db):
    DeleteParent.query.create(name="a")
    DeleteParent.query.create(name="b")
    DeleteParent.query.create(name="c")

    assert DeleteParent.query.all().delete() == 3


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
    count = DeleteParent.query.order_by("name").delete()
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
    widget = Widget.query.create(name="Ford", size="F150")
    tag_a = Tag.query.create(name="4wd")
    tag_b = Tag.query.create(name="towing")
    widget.tags.add(tag_a, tag_b)

    widget.tags.remove(tag_a)

    assert WidgetTag.query.filter(widget=widget).count() == 1
    assert WidgetTag.query.filter(widget=widget, tag=tag_b).exists()
    assert Tag.query.filter(id=tag_a.id).exists()


def test_m2m_clear_deletes_all_through_rows(db):
    widget = Widget.query.create(name="Ford", size="F150")
    tag_a = Tag.query.create(name="4wd")
    tag_b = Tag.query.create(name="towing")
    widget.tags.add(tag_a, tag_b)

    widget.tags.clear()

    assert WidgetTag.query.filter(widget=widget).count() == 0
    assert Tag.query.count() == 2


def test_m2m_set_reconciles_through_rows(db):
    widget = Widget.query.create(name="Ford", size="F150")
    a = Tag.query.create(name="a")
    b = Tag.query.create(name="b")
    c = Tag.query.create(name="c")
    widget.tags.add(a, b)

    widget.tags.set([b, c])

    tag_ids = set(
        WidgetTag.query.filter(widget=widget).values_list("tag_id", flat=True)
    )
    assert tag_ids == {b.id, c.id}


# ===========================================================================
# 7. Idempotency
# ===========================================================================


def test_delete_already_deleted_instance_raises(db):
    """After `.delete()`, Plain sets `instance.id = None`. A second `.delete()`
    raises ValueError."""
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    parent.delete()

    with pytest.raises(ValueError, match="id attribute is set to None"):
        parent.delete()


# ===========================================================================
# 8. Query-count canary
# ===========================================================================


def test_cascade_delete_issues_one_query(db):
    """Single-level CASCADE fires exactly one DELETE — Postgres handles the
    cascade internally. This is the headline win of the DB-level rewrite."""
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

    assert query_count == 1, (
        f"Expected one DELETE; got {query_count} queries — Collector may have "
        f"crept back, or _raw_delete lost its single-statement property."
    )


# ===========================================================================
# 9. db_constraint=False requires on_delete=NO_ACTION (preflight)
# ===========================================================================


def test_unconstrained_with_cascade_is_rejected_at_preflight():
    """db_constraint=False has no FK constraint to attach on_delete to, so
    anything other than NO_ACTION is rejected at model-check."""
    from plain import postgres
    from plain.postgres.fields.related import ForeignKeyField

    field = ForeignKeyField(
        DeleteParent, on_delete=postgres.CASCADE, db_constraint=False
    )
    field.set_attributes_from_name("parent")
    field.model = UnconstrainedChild
    results = field._check_on_delete()

    assert any(
        r.id == "fields.foreign_key_unconstrained_requires_no_action" for r in results
    )


def test_instance_delete_bypasses_custom_query_filters(db):
    """An instance you hold a reference to must always be deletable, even if
    the model's public `query` descriptor applies a default filter that would
    exclude it (e.g. soft-delete scopes, tenant filtering). Model.delete()
    uses `_model_meta.base_queryset` to route around custom filtering.
    """
    ghost = HideableItem(name="ghost")
    ghost.save()
    visible = HideableItem(name="visible")
    visible.save()

    # Public queryset filters out ghost rows by default
    assert HideableItem.query.filter(id=ghost.id).count() == 0
    assert HideableItem.query.filter(id=visible.id).count() == 1

    # But instance.delete() bypasses the filter — ghost is deleted
    assert ghost.delete() == 1

    # Row is actually gone (verify via base_queryset which skips the filter)
    assert not HideableItem._model_meta.base_queryset.filter(id=ghost.id).exists()


def test_on_delete_must_be_sentinel():
    """Passing a non-OnDelete value raises TypeError at FK construction."""
    from plain.postgres.fields.related import ForeignKeyField

    with pytest.raises(TypeError, match="on_delete must be one of"):
        ForeignKeyField(DeleteParent, on_delete=lambda *a: None)  # ty: ignore[invalid-argument-type]
