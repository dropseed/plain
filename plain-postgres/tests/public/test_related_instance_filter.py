"""Filtering a queryset by a related *instance* (or a list of them).

Exercises the related-lookup prep path for every kind of relation that can be
the lookup target. The prep path reads ``output_field.target_field`` to find
the column to compare against, so each relation type (ForeignKeyField,
ForeignKeyRel, ManyToManyField, ManyToManyRel) must expose ``target_field``.
"""

from __future__ import annotations

from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.relationships import Tag, Widget


def test_forward_fk_filter_by_instance():
    parent = DeleteParent(name="p")
    parent.create()
    child = ChildCascade(parent=parent)
    child.create()

    assert list(ChildCascade.query.filter(parent=parent)) == [child]


def test_reverse_fk_filter_by_instance():
    parent = DeleteParent(name="p")
    parent.create()
    child = ChildCascade(parent=parent)
    child.create()

    assert list(DeleteParent.query.filter(childcascade=child)) == [parent]


def test_reverse_fk_filter_in():
    parent = DeleteParent(name="p")
    parent.create()
    child = ChildCascade(parent=parent)
    child.create()

    assert list(DeleteParent.query.filter(childcascade__in=[child])) == [parent]


def test_forward_m2m_filter_by_instance():
    widget = Widget(name="w", size="m")
    widget.create()
    tag = Tag(name="t")
    tag.create()
    widget.tags.add(tag)

    assert list(Widget.query.filter(tags=tag)) == [widget]


def test_reverse_m2m_filter_by_instance():
    widget = Widget(name="w", size="m")
    widget.create()
    tag = Tag(name="t")
    tag.create()
    widget.tags.add(tag)

    # Reverse M2M query name defaults to the source model name ("widget").
    assert list(Tag.query.filter(widget=widget)) == [tag]


# exclude() across a to-many relation goes through Query.split_exclude ->
# trim_start, a distinct subquery-building path from the filter() lookups above.


def test_exclude_across_reverse_fk():
    p1 = DeleteParent(name="p1")
    p1.create()
    child = ChildCascade(parent=p1)
    child.create()
    p2 = DeleteParent(name="p2")
    p2.create()

    # Parents that do NOT have this child: p1 has it, p2 does not.
    assert set(DeleteParent.query.exclude(childcascade=child)) == {p2}


def test_exclude_across_m2m():
    w1 = Widget(name="w1", size="m")
    w1.create()
    tag = Tag(name="t")
    tag.create()
    w1.tags.add(tag)
    w2 = Widget(name="w2", size="m")
    w2.create()

    # Widgets NOT tagged with `tag`: w1 is, w2 is not.
    assert set(Widget.query.exclude(tags=tag)) == {w2}
