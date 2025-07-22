import pytest
from app.examples.models import (
    ChildCascade,
    ChildProtect,
    ChildRestrict,
    ChildSetDefault,
    ChildSetNull,
    DeleteParent,
)

from plain.models import (
    ProtectedError,
    RestrictedError,
)


def _create_parents():
    default_parent = DeleteParent.objects.create(name="default")
    parent = DeleteParent.objects.create(name="parent")
    return default_parent, parent


def test_cascade_delete(db):
    _create_parents()
    parent = DeleteParent.objects.get(name="parent")
    ChildCascade.objects.create(parent=parent)
    parent.delete()
    assert ChildCascade.objects.count() == 0


def test_protect_delete(db):
    _create_parents()
    parent = DeleteParent.objects.get(name="parent")
    ChildProtect.objects.create(parent=parent)
    with pytest.raises(ProtectedError):
        parent.delete()
    assert DeleteParent.objects.filter(id=parent.id).exists()


def test_restrict_delete(db):
    _create_parents()
    parent = DeleteParent.objects.get(name="parent")
    ChildRestrict.objects.create(parent=parent)
    with pytest.raises(RestrictedError):
        parent.delete()
    assert DeleteParent.objects.filter(id=parent.id).exists()


def test_set_null_delete(db):
    _create_parents()
    parent = DeleteParent.objects.get(name="parent")
    child = ChildSetNull.objects.create(parent=parent)
    parent.delete()
    child.refresh_from_db()
    assert child.parent_id is None


def test_set_default_delete(db):
    default_parent, parent = _create_parents()
    child = ChildSetDefault.objects.create(parent=parent)
    parent.delete()
    child.refresh_from_db()
    assert child.parent_id == default_parent.id


# def test_do_nothing_delete(db):
#     default_parent, parent = _create_parents()
#     child = ChildDoNothing.objects.create(parent=parent)
#     parent.delete()
#     with pytest.raises(IntegrityError):
#         db_connection.check_constraints()
#     child.parent = default_parent
#     child.save(clean_and_validate=False)
