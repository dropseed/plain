"""Characterization of foreign key behavior.

This file pins how foreign keys currently behave -- forward access, the
``<name>_id`` attribute, construction, assignment, and querying -- so that any
future change to the foreign key implementation shows up as a diff to these
tests.
"""

from __future__ import annotations

import pytest
from app.examples.models.delete import ChildCascade, CircA, DeleteParent

# ===========================================================================
# Forward relation -- accessing the related object.
# ===========================================================================


def test_forward_access_returns_related_object(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    fetched = ChildCascade.query.get(id=child.id)
    assert isinstance(fetched.parent, DeleteParent)
    assert fetched.parent == parent
    assert fetched.parent.name == "P"


def test_construct_with_related_object(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade(parent=parent)
    child.save()
    assert ChildCascade.query.get(id=child.id).parent == parent


def test_reassign_related_object(db):
    p1 = DeleteParent.query.create(name="P1")
    p2 = DeleteParent.query.create(name="P2")
    child = ChildCascade.query.create(parent=p1)
    child.parent = p2
    child.save()
    assert ChildCascade.query.get(id=child.id).parent == p2


def test_filter_by_related_object(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    assert ChildCascade.query.filter(parent=parent).get() == child


def test_filter_by_related_field_lookup(db):
    parent = DeleteParent.query.create(name="P")
    ChildCascade.query.create(parent=parent)
    assert ChildCascade.query.filter(parent__name="P").exists()


def test_select_related(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    fetched = ChildCascade.query.select_related("parent").get(id=child.id)
    assert fetched.parent.name == "P"


def test_nullable_fk_none(db):
    # CircA.partner is allow_null=True, required=False -- a genuinely optional FK.
    obj = CircA.query.create(name="a")
    assert CircA.query.get(id=obj.id).partner is None


def test_save_roundtrip(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    reloaded = ChildCascade.query.get(id=child.id)
    reloaded.save()
    assert ChildCascade.query.get(id=child.id).parent == parent


# ===========================================================================
# The "<name>_id" attribute and field name.
# ===========================================================================


def test_id_attribute_read(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    # parent_id is not visible to the type checker (the field is typed as the
    # related object) -- exercised here for runtime behavior only.
    assert ChildCascade.query.get(id=child.id).parent_id == parent.id  # ty: ignore[unresolved-attribute]


def test_construct_with_id_kwarg(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade(parent_id=parent.id)
    child.save()
    assert ChildCascade.query.get(id=child.id).parent == parent


def test_id_attribute_write(db):
    p1 = DeleteParent.query.create(name="P1")
    p2 = DeleteParent.query.create(name="P2")
    child = ChildCascade.query.create(parent=p1)
    child.parent_id = p2.id  # ty: ignore[unresolved-attribute]
    child.save()
    assert ChildCascade.query.get(id=child.id).parent == p2


def test_assign_bare_int(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    # Assigning a bare key value is rejected -- only instances are accepted.
    with pytest.raises(ValueError, match="Cannot assign"):
        child.parent = parent.id  # ty: ignore[invalid-assignment]


def test_filter_by_id(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    assert ChildCascade.query.filter(parent_id=parent.id).get() == child


def test_values_id(db):
    parent = DeleteParent.query.create(name="P")
    ChildCascade.query.create(parent=parent)
    rows = list(ChildCascade.query.values("parent_id"))
    assert rows[0]["parent_id"] == parent.id


def test_values_list_id(db):
    parent = DeleteParent.query.create(name="P")
    ChildCascade.query.create(parent=parent)
    assert list(ChildCascade.query.values_list("parent_id", flat=True)) == [parent.id]


def test_only_id(db):
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    fetched = ChildCascade.query.only("parent_id").get(id=child.id)
    assert fetched.parent_id == parent.id  # ty: ignore[unresolved-attribute]
