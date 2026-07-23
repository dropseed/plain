"""Typed where() across forward foreign-key relations.

`ChildCascade.parent` is a ForeignKeyField to DeleteParent. Accessing
`.name` on the class-level descriptor should yield a PrefixedFieldRef
whose typed-query methods build Q objects with `parent__name` paths.
"""

from __future__ import annotations

import pytest
from app.examples.models.delete import (
    ChildCascade,
    DeleteParent,
    Grandchild,
    Grandparent,
    MidParent,
)
from app.examples.models.encrypted import SecretStore
from app.examples.models.relationships import Tag, Widget, WidgetTag
from app.examples.models.shadowing import ShadowSource, ShadowTarget

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
    assert ChildCascade.parent.name.is_in(["a", "b"]).children == [
        ("parent__name__in", ["a", "b"])
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
    with pytest.raises(AttributeError):
        ChildCascade.parent.nonexistent_field  # ty: ignore[unresolved-attribute]


# ---------------------------------------------------------------------------
# Multi-hop traversal: Grandchild -> MidParent -> Grandparent
# ---------------------------------------------------------------------------


def test_two_hop_traversal_builds_double_prefixed_q():
    q = Grandchild.mid_parent.grandparent.name.equals("alice")
    assert q.children == [("mid_parent__grandparent__name", "alice")]


def test_two_hop_traversal_runs(db):
    g1 = Grandparent.query.create(name="alice")
    g2 = Grandparent.query.create(name="bob")
    m1 = MidParent.query.create(grandparent=g1)
    m2 = MidParent.query.create(grandparent=g2)
    Grandchild.query.create(mid_parent=m1)
    Grandchild.query.create(mid_parent=m2)

    matches = list(
        Grandchild.query.where(Grandchild.mid_parent.grandparent.name.equals("alice"))
    )
    assert {gc.mid_parent.grandparent.name for gc in matches} == {"alice"}


def test_two_hop_chain_combines_with_or(db):
    g1 = Grandparent.query.create(name="alice")
    g2 = Grandparent.query.create(name="bob")
    g3 = Grandparent.query.create(name="carol")
    m1 = MidParent.query.create(grandparent=g1)
    m2 = MidParent.query.create(grandparent=g2)
    m3 = MidParent.query.create(grandparent=g3)
    Grandchild.query.create(mid_parent=m1)
    Grandchild.query.create(mid_parent=m2)
    Grandchild.query.create(mid_parent=m3)

    matches = list(
        Grandchild.query.where(
            Grandchild.mid_parent.grandparent.name.equals("alice")
            | Grandchild.mid_parent.grandparent.name.startswith("c")
        )
    )
    assert {gc.mid_parent.grandparent.name for gc in matches} == {"alice", "carol"}


# ---------------------------------------------------------------------------
# Encrypted field traversal — comparison must be rejected, mirroring the
# direct-access behavior added in the previous commit.
# ---------------------------------------------------------------------------


class TestEncryptedFieldTraversalBlocked:
    """A model with an FK to an encrypted-field-bearing model. Direct access
    (SecretStore.api_key.equals) raises TypeError. Traversal must too —
    otherwise the typed-API guard becomes a per-call-site instead of a
    per-field guarantee."""

    def test_traversed_equals_raises(self, db):
        # WidgetTag doesn't have an FK to SecretStore, so we construct a
        # synthetic traversal via PrefixedFieldRef directly. This is the
        # same code path Order.relation.api_key.equals(...) would use.
        from plain.postgres.fields.related_typed import PrefixedFieldRef

        ref = PrefixedFieldRef(
            field=SecretStore._model_meta.get_field("api_key"),
            prefix="store__api_key",
        )
        with pytest.raises(
            TypeError, match=r"Encrypted field.*does not support \.equals\("
        ):
            ref.equals("x")

    def test_traversed_ordering_raises(self):
        from plain.postgres.fields.related_typed import PrefixedFieldRef

        ref = PrefixedFieldRef(
            field=SecretStore._model_meta.get_field("api_key"),
            prefix="store__api_key",
        )
        for method in ("not_equal", "gt", "gte", "lt", "lte", "contains"):
            with pytest.raises(TypeError, match=rf"does not support \.{method}\("):
                getattr(ref, method)("x")

    def test_traversed_is_in_raises(self):
        from plain.postgres.fields.related_typed import PrefixedFieldRef

        ref = PrefixedFieldRef(
            field=SecretStore._model_meta.get_field("api_key"),
            prefix="store__api_key",
        )
        with pytest.raises(TypeError, match=r"does not support \.is_in\("):
            ref.is_in(["x", "y"])

    def test_traversed_is_null_still_works(self):
        from plain.postgres.fields.related_typed import PrefixedFieldRef

        ref = PrefixedFieldRef(
            field=SecretStore._model_meta.get_field("api_key"),
            prefix="store__api_key",
        )
        q = ref.is_null()
        assert q.children == [("store__api_key__isnull", True)]


# ---------------------------------------------------------------------------
# Descriptor attribute shadowing: a related field whose name collides with a
# public attribute on ForwardForeignKeyDescriptor (`field`, `is_cached`,
# `get_queryset`, `get_prefetch_queryset`) must still traverse to the field.
# `__get__` returns a RelatedFieldRef proxy for class access, so the
# descriptor's own attributes are unreachable through the relation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["field", "is_cached", "get_queryset", "get_prefetch_queryset"],
)
def test_shadowed_field_name_traverses_to_field(name):
    """ShadowTarget defines fields named after descriptor attributes.
    Traversal through ShadowSource.ref resolves each to the field, building
    a `ref__<name>` path rather than returning the descriptor's attribute."""
    ref = getattr(ShadowSource.ref, name)
    q = ref.equals("x")
    assert q.children == [(f"ref__{name}", "x")]


def test_shadowed_field_traversal_runs(db):
    """End-to-end: a where() through the shadowed `field` name filters rows."""
    matched = ShadowTarget.query.create(
        field="hit",
        is_cached="a",
        get_queryset="b",
        get_prefetch_queryset="c",
    )
    ShadowTarget.query.create(
        field="miss",
        is_cached="a",
        get_queryset="b",
        get_prefetch_queryset="c",
    )
    ShadowSource.query.create(ref=matched)

    rows = list(ShadowSource.query.where(ShadowSource.ref.field.equals("hit")))
    assert [r.ref.id for r in rows] == [matched.id]
