"""Characterization of foreign key behavior.

This file pins how foreign keys currently behave -- forward access, the
``<name>_id`` attribute, construction, assignment, and querying -- so that any
future change to the foreign key implementation shows up as a diff to these
tests.
"""

from __future__ import annotations

from app.examples.models.delete import ChildCascade, CircA, DeleteParent

from plain.postgres.exceptions import FieldDoesNotExist, FieldError
from plain.test import raises

# ===========================================================================
# Forward relation -- accessing the related object.
# ===========================================================================


def test_forward_access_returns_related_object():
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    fetched = ChildCascade.query.get(id=child.id)
    assert isinstance(fetched.parent, DeleteParent)
    assert fetched.parent == parent
    assert fetched.parent.name == "P"


def test_construct_with_related_object():
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade(parent=parent)
    child.create()
    assert ChildCascade.query.get(id=child.id).parent == parent


def test_reassign_related_object():
    p1 = DeleteParent.query.create(name="P1")
    p2 = DeleteParent.query.create(name="P2")
    child = ChildCascade.query.create(parent=p1)
    child.parent = p2
    child.update()
    assert ChildCascade.query.get(id=child.id).parent == p2


def test_filter_by_related_object():
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    assert ChildCascade.query.filter(parent=parent).get() == child


def test_filter_by_related_field_lookup():
    parent = DeleteParent.query.create(name="P")
    ChildCascade.query.create(parent=parent)
    assert ChildCascade.query.filter(parent__name="P").exists()


def test_select_related():
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    fetched = ChildCascade.query.select_related("parent").get(id=child.id)
    assert fetched.parent.name == "P"


def test_nullable_fk_none():
    # CircA.partner is allow_null=True, required=False -- a genuinely optional FK.
    obj = CircA.query.create(name="a")
    assert CircA.query.get(id=obj.id).partner is None


def test_save_roundtrip():
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    reloaded = ChildCascade.query.get(id=child.id)
    reloaded.update()
    assert ChildCascade.query.get(id=child.id).parent == parent


# ===========================================================================
# The "<name>_id" attribute and field name.
# ===========================================================================


def test_id_attribute_read():
    # WAS: child.parent_id returned the raw key int.
    # NOW: there is no parent_id attribute -- read child.parent.id.
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.get(id=ChildCascade.query.create(parent=parent).id)
    with raises(AttributeError, match="parent_id"):
        _ = child.parent_id  # ty: ignore[unresolved-attribute]
    assert child.parent.id == parent.id


def test_construct_with_id_kwarg():
    # WAS: ChildCascade(parent_id=n) constructed by raw key.
    # NOW: TypeError -- pass the field name, which also accepts a bare key.
    parent = DeleteParent.query.create(name="P")
    with raises(TypeError, match="unexpected keyword"):
        ChildCascade(parent_id=parent.id)
    child = ChildCascade(parent=parent.id)
    child.create()
    assert ChildCascade.query.get(id=child.id).parent == parent


def test_id_attribute_write():
    # WAS: child.parent_id = n updated the foreign key.
    # NOW: it neither errors nor updates the key -- it sets an ignored
    # attribute. This is the one breaking change that fails silently; assign
    # the field directly (child.parent = n) instead.
    p1 = DeleteParent.query.create(name="P1")
    p2 = DeleteParent.query.create(name="P2")
    child = ChildCascade.query.create(parent=p1)
    child.parent_id = p2.id  # ty: ignore[unresolved-attribute]
    child.update()
    assert ChildCascade.query.get(id=child.id).parent == p1  # unchanged!


def test_assign_bare_int():
    # WAS: child.parent = <int> raised ValueError (only instances allowed).
    # NOW: a bare primary key value is accepted.
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    child.parent = parent.id
    assert child.parent.id == parent.id


def test_filter_by_id():
    # WAS: .filter(parent_id=n) resolved. NOW: FieldError -- use `parent`.
    parent = DeleteParent.query.create(name="P")
    ChildCascade.query.create(parent=parent)
    with raises(FieldError):
        ChildCascade.query.filter(parent_id=parent.id).exists()


def test_values_id():
    # WAS: .values("parent_id") resolved. NOW: it does not -- use "parent".
    parent = DeleteParent.query.create(name="P")
    ChildCascade.query.create(parent=parent)
    with raises(FieldError, FieldDoesNotExist):
        list(ChildCascade.query.values("parent_id"))


def test_values_list_id():
    # WAS: .values_list("parent_id") resolved. NOW: it does not.
    parent = DeleteParent.query.create(name="P")
    ChildCascade.query.create(parent=parent)
    with raises(FieldError, FieldDoesNotExist):
        list(ChildCascade.query.values_list("parent_id", flat=True))


def test_only_id():
    # WAS: .only("parent_id") resolved. NOW: it does not -- use "parent".
    parent = DeleteParent.query.create(name="P")
    child = ChildCascade.query.create(parent=parent)
    with raises(FieldError, FieldDoesNotExist):
        ChildCascade.query.only("parent_id").get(id=child.id)
