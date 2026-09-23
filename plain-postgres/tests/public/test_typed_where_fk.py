"""Typed where() across forward foreign-key relations.

`ChildCascade.parent` is a ForeignKeyField to DeleteParent. Accessing
`.name` on the class-level descriptor should yield DeleteParent's own `name`
field, renamed to `parent__name`, so its condition methods build that path.
"""

import pytest
from app.examples.models.delete import (
    ChildCascade,
    ChildSetNull,
    DeleteParent,
    Grandchild,
    Grandparent,
    MidParent,
)
from app.examples.models.relationships import Tag, Widget, WidgetTag
from app.examples.models.shadowing import ShadowSource, ShadowTarget
from plain.postgres import Q


def test_fk_field_access_builds_prefixed_q():
    q = ChildCascade.parent.name.equals("foo")
    assert isinstance(q, Q)
    assert q.children == [("parent__name", "foo")]


def test_lookup_path_is_the_column_name_or_the_traversed_path():
    """The path generic code puts before a lookup suffix.

    Static half: tests/typing/field_access.py, relations_foreign_key.py.
    """
    assert DeleteParent.name.lookup_path == "name"
    assert ChildCascade.parent.name.lookup_path == "parent__name"
    assert Grandchild.mid_parent.grandparent.name.lookup_path == (
        "mid_parent__grandparent__name"
    )


def test_fk_field_access_supports_other_lookups():
    assert ChildCascade.parent.name.startswith("a").children == [
        ("parent__name__startswith", "a")
    ]
    assert ChildCascade.parent.name.is_null().children == [
        ("parent__name__isnull", True)
    ]
    assert ChildCascade.parent.name.is_in(["a", "b"]).children == [
        ("parent__name__any_of", ["a", "b"])
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
        _ = ChildCascade.parent.nonexistent_field  # ty: ignore[unresolved-attribute]


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


# ---------------------------------------------------------------------------
# Descriptor attribute shadowing: these four names were once public attributes
# on ForwardForeignKeyDescriptor, so a related field named after one of them
# resolved to the descriptor's attribute instead of traversing. They are
# `_`-prefixed now, and `Meta` skips `_`-prefixed attributes when it collects
# fields, so no field name can ever collide with a descriptor attribute again.
# These cases pin that: re-publishing any of them would fail here.
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


# ---------------------------------------------------------------------------
# Conditions on the relation itself.
#
# A relation is not a field, so it has no condition methods -- and it can't be
# given any. To the type checker `ChildCascade.parent` is `type[DeleteParent]`
# (Field.__get__'s model-valued overloads), which is exactly what lets chained
# traversal type-check; a runtime `.equals()` the checker rejects would be
# worse than none. The spelling is traversal to the key the relation targets,
# which compiles to the same lookup `filter(parent=obj)` produces.
# ---------------------------------------------------------------------------


def test_relation_key_conditions_build_q():
    assert ChildCascade.parent.id.equals(7).children == [("parent__id", 7)]
    assert ChildCascade.parent.id.is_in([1, 2]).children == [
        ("parent__id__any_of", [1, 2])
    ]
    assert ChildSetNull.parent.id.is_null().children == [("parent__id__isnull", True)]
    assert ChildCascade.parent.id.not_equal(7).children == [("parent__id", 7)]


def test_where_filters_by_relation_key(db):
    kept = DeleteParent.query.create(name="kept")
    other = DeleteParent.query.create(name="other")
    mine = ChildCascade.query.create(parent=kept)
    ChildCascade.query.create(parent=other)

    rows = list(ChildCascade.query.where(ChildCascade.parent.id.equals(kept.id)))
    assert [r.id for r in rows] == [mine.id]


def test_relation_key_matches_filter_on_the_relation(db):
    """The documented equivalence: traversing to the key is the typed spelling
    of `filter(parent=obj)`, not merely something similar."""
    kept = DeleteParent.query.create(name="kept")
    other = DeleteParent.query.create(name="other")
    ChildCascade.query.create(parent=kept)
    ChildCascade.query.create(parent=other)

    typed = [
        r.id for r in ChildCascade.query.where(ChildCascade.parent.id.equals(kept.id))
    ]
    untyped = [r.id for r in ChildCascade.query.filter(parent=kept)]
    assert typed == untyped
    assert len(typed) == 1


def test_where_filters_by_relation_key_is_in(db):
    a = DeleteParent.query.create(name="a")
    b = DeleteParent.query.create(name="b")
    c = DeleteParent.query.create(name="c")
    for parent in (a, b, c):
        ChildCascade.query.create(parent=parent)

    rows = list(ChildCascade.query.where(ChildCascade.parent.id.is_in([a.id, c.id])))
    assert sorted(r.parent.id for r in rows) == sorted([a.id, c.id])


def test_where_filters_by_null_relation_key(db):
    kept = DeleteParent.query.create(name="kept")
    doomed = DeleteParent.query.create(name="doomed")
    attached = ChildSetNull.query.create(parent=kept)
    orphan = ChildSetNull.query.create(parent=doomed)

    # The field is nullable but still `required`, so the null arrives the way
    # it does in practice: SET_NULL clearing the key when the parent goes.
    DeleteParent.query.filter(id=doomed.id).delete()

    nulls = list(ChildSetNull.query.where(ChildSetNull.parent.id.is_null()))
    assert [r.id for r in nulls] == [orphan.id]

    non_nulls = list(ChildSetNull.query.where(ChildSetNull.parent.id.is_null(False)))
    assert [r.id for r in non_nulls] == [attached.id]


@pytest.mark.parametrize("method", ["equals", "is_in", "is_null", "gte", "contains"])
def test_condition_on_the_relation_itself_raises_helpful_error(method):
    """An AttributeError, so `hasattr`/`getattr(..., default)` keep working --
    but one that names the spelling that does work, or the constraint just
    looks like a missing feature. (The sweep across every condition name is in
    tests/internal/test_typed_where_internals.py.)"""
    with pytest.raises(AttributeError) as excinfo:
        getattr(ChildCascade.parent, method)

    message = str(excinfo.value)
    assert "is a relation, not a field" in message
    assert f"parent.id.{method}(...)" in message


def test_condition_on_the_relation_keeps_the_attribute_protocol():
    assert not hasattr(ChildCascade.parent, "equals")
    assert getattr(ChildCascade.parent, "equals", "fallback") == "fallback"


def test_unknown_relation_attribute_still_raises_attribute_error():
    """A genuine typo gets the plain "not a traversable field" message rather
    than the condition-method advice."""
    with pytest.raises(AttributeError, match="parent.nope is not a traversable"):
        getattr(ChildCascade.parent, "nope")


def test_related_field_named_like_a_condition_still_traverses():
    """The field lookup runs first, so a related model that really does have a
    column named after a condition method still resolves to the column."""
    assert ShadowSource.ref.field.equals("hit").children == [("ref__field", "hit")]


# ---------------------------------------------------------------------------
# Many-to-many relations traverse like any other. Reached *through* a relation,
# `widget__tags__name` is as valid a lookup path as `widget__author__name`, so
# an M2M is a hop, not a leaf -- handing the M2M field back renamed would make
# `.name` resolve to the string "widget__tags".
#
# (Direct class access, `Widget.tags`, is a ForwardManyToManyDescriptor and has
# no traversal wiring; this branch covers forward-FK traversal only.)
#
# This hop is runtime-only for now: at the type level `tags` is declared
# `ManyToManyManager[Tag]`, which exposes the manager API, not the target
# model's fields. Typing it would mean claiming class access to an M2M yields
# `type[Tag]` -- true after a traversal hop, false for `Widget.tags` itself --
# so the ignores below are the honest marker rather than a papered-over bug.
# ---------------------------------------------------------------------------


def test_m2m_traversal_through_a_foreign_key():
    q = WidgetTag.widget.tags.name.equals(  # ty: ignore[unresolved-attribute]
        "metal"
    )
    assert q.children == [("widget__tags__name", "metal")]


def test_condition_on_a_traversed_m2m_gets_the_same_advice():
    with pytest.raises(AttributeError) as excinfo:
        getattr(WidgetTag.widget.tags, "equals")

    message = str(excinfo.value)
    assert "is a relation, not a field" in message
    assert "WidgetTag.widget.tags" not in message  # the prefix, not the model
    assert "widget.tags.id.equals(...)" in message


def test_where_filters_through_a_foreign_key_then_an_m2m(db):
    metal = Tag.query.create(name="metal")
    plastic = Tag.query.create(name="plastic")
    cog = Widget.query.create(name="cog", size="small")
    knob = Widget.query.create(name="knob", size="small")
    WidgetTag.query.create(widget=cog, tag=metal)
    WidgetTag.query.create(widget=knob, tag=plastic)

    condition = WidgetTag.widget.tags.name.equals(  # ty: ignore[unresolved-attribute]
        "metal"
    )
    rows = list(WidgetTag.query.where(condition))
    assert [r.widget.id for r in rows] == [cog.id]


def test_reverse_relation_says_it_is_not_traversable():
    """`filter(parent__childcascade_set__...)` works, so "not a traversable
    field or relation" would be a lie -- the typed API is what can't express
    it, and the message has to say which."""
    with pytest.raises(AttributeError) as excinfo:
        getattr(ChildCascade.parent, "childcascade_set")

    message = str(excinfo.value)
    assert "reverse relation" in message
    assert "filter(parent__childcascade_set__...=...)" in message


class TestTraversedConditionsBelongToTheirRoot:
    """A traversed condition belongs to the model the traversal *started* from,
    not the related model the column lives on. `ChildCascade.parent.name`
    builds `parent__name`, which only means anything to a `ChildCascade`
    queryset -- so that is the model `where()` checks it against."""

    def test_traversed_condition_passes_on_its_root(self, db):
        parent = DeleteParent.query.create(name="p")
        ChildCascade.query.create(parent=parent)
        rows = ChildCascade.query.where(ChildCascade.parent.name.equals("p"))
        assert len(list(rows)) == 1

    def test_traversed_condition_raises_on_another_model(self, db):
        """`parent__name` is meaningless to DeleteParent, and the root is what
        the error names -- not DeleteParent, whose column it actually is."""
        with pytest.raises(TypeError) as excinfo:
            DeleteParent.query.where(ChildCascade.parent.name.equals("p"))
        message = str(excinfo.value)
        assert "ChildCascade.parent__name" in message
        assert "DeleteParent queryset" in message

    def test_traversed_condition_is_not_the_related_models(self, db):
        """The tempting wrong answer: treating the condition as DeleteParent's
        because that is where `name` is declared."""
        with pytest.raises(TypeError, match="ChildCascade.parent__name"):
            DeleteParent.query.where(ChildCascade.parent.name.equals("p"))

    def test_multi_hop_traversal_keeps_the_root(self, db):
        """Every hop carries the root unchanged, so a two-hop path is still
        Grandchild's."""
        grandparent = Grandparent.query.create(name="g")
        mid = MidParent.query.create(grandparent=grandparent)
        Grandchild.query.create(mid_parent=mid)

        rows = Grandchild.query.where(
            Grandchild.mid_parent.grandparent.name.equals("g")
        )
        assert len(list(rows)) == 1

        with pytest.raises(TypeError, match="Grandchild.mid_parent__grandparent__name"):
            MidParent.query.where(Grandchild.mid_parent.grandparent.name.equals("g"))

    def test_traversed_and_local_conditions_combine_on_the_root(self, db):
        parent = DeleteParent.query.create(name="p")
        ChildCascade.query.create(parent=parent)
        rows = ChildCascade.query.where(
            ChildCascade.parent.name.equals("p") & ChildCascade.id.gte(1)
        )
        assert len(list(rows)) == 1
