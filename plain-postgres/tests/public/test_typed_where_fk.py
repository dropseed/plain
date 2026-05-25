"""Typed where() across forward foreign-key relations.

`ChildCascade.parent` is a ForeignKeyField to DeleteParent. Accessing
`.name` on the class-level descriptor should yield a PrefixedFieldRef
whose typed-query methods build Q objects with `parent__name` paths.
"""

from __future__ import annotations

from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.relationships import Tag, Widget, WidgetTag

from plain.postgres.query_utils import Q


def test_fk_field_access_builds_prefixed_q():
    q = ChildCascade.parent.name.equals("foo")
    assert isinstance(q, Q)
    assert q.children == [("parent__name", "foo")]


def test_fk_field_access_supports_other_lookups():
    assert ChildCascade.parent.name.startswith("a").children == [
        ("parent__name__startswith", "a")
    ]
    assert ChildCascade.parent.name.is_null().children == [
        ("parent__name__isnull", True)
    ]


def test_fk_traversal_in_where_clause(db):
    """End-to-end: build a query through the FK and verify it runs."""
    parent = DeleteParent.query.create(name="alice")
    other = DeleteParent.query.create(name="bob")
    ChildCascade.query.create(parent=parent)
    ChildCascade.query.create(parent=other)

    matches = list(ChildCascade.query.where(ChildCascade.parent.name.equals("alice")))
    assert len(matches) == 1
    assert matches[0].parent.id == parent.id


def test_fk_traversal_combines_with_local_conditions(db):
    """Mix a traversal condition with a local condition via &."""
    p1 = DeleteParent.query.create(name="alice")
    p2 = DeleteParent.query.create(name="alice")
    ChildCascade.query.create(parent=p1)
    ChildCascade.query.create(parent=p2)

    matches = list(
        ChildCascade.query.where(
            ChildCascade.parent.name.equals("alice"),
            ChildCascade.id.gte(0),
        )
    )
    assert {c.parent.id for c in matches} == {p1.id, p2.id}


def test_multiple_fks_on_one_model(db):
    """WidgetTag has FKs to both Widget and Tag — each path resolves independently."""
    w = Widget.query.create(name="cog", size="small")
    t = Tag.query.create(name="metal")
    WidgetTag.query.create(widget=w, tag=t)

    assert WidgetTag.query.where(WidgetTag.widget.name.equals("cog")).count() == 1
    assert WidgetTag.query.where(WidgetTag.tag.name.equals("metal")).count() == 1
    assert WidgetTag.query.where(WidgetTag.widget.name.equals("missing")).count() == 0


def test_fk_traversal_or_combination(db):
    p1 = DeleteParent.query.create(name="alice")
    p2 = DeleteParent.query.create(name="bob")
    p3 = DeleteParent.query.create(name="carol")
    ChildCascade.query.create(parent=p1)
    ChildCascade.query.create(parent=p2)
    ChildCascade.query.create(parent=p3)

    matches = list(
        ChildCascade.query.where(
            ChildCascade.parent.name.equals("alice")
            | ChildCascade.parent.name.equals("carol")
        )
    )
    assert {c.parent.name for c in matches} == {"alice", "carol"}


def test_unknown_attribute_on_related_raises_attribute_error():
    """Traversal into a non-existent field on the related model fails loudly,
    not silently producing a wrong-shaped Q."""
    import pytest

    with pytest.raises(AttributeError):
        ChildCascade.parent.nonexistent_field  # ty: ignore[unresolved-attribute]
