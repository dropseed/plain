import pytest
from app.examples.models import (  # type: ignore[import-untyped]
    ChildCascade,
    ChildProtect,
    ChildRestrict,
    ChildSetDefault,
    ChildSetNull,
    DeleteParent,
)

from plain.models.deletion import ProtectedError, RestrictedError


def _create_parents():
    default_parent = DeleteParent.query.create(name="default")
    parent = DeleteParent.query.create(name="parent")
    return default_parent, parent


def test_cascade_delete(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildCascade.query.create(parent=parent)
    parent.delete()
    assert ChildCascade.query.count() == 0


def test_protect_delete(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildProtect.query.create(parent=parent)
    with pytest.raises(ProtectedError):
        parent.delete()
    assert DeleteParent.query.filter(id=parent.id).exists()


def test_restrict_delete(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    ChildRestrict.query.create(parent=parent)
    with pytest.raises(RestrictedError):
        parent.delete()
    assert DeleteParent.query.filter(id=parent.id).exists()


def test_set_null_delete(db):
    _create_parents()
    parent = DeleteParent.query.get(name="parent")
    child = ChildSetNull.query.create(parent=parent)
    parent.delete()
    child.refresh_from_db()
    assert child.parent_id is None


def test_set_default_delete(db):
    default_parent, parent = _create_parents()
    child = ChildSetDefault.query.create(parent=parent)
    parent.delete()
    child.refresh_from_db()
    assert child.parent_id == default_parent.id


# def test_do_nothing_delete(db):
#     default_parent, parent = _create_parents()
#     child = ChildDoNothing.query.create(parent=parent)
#     parent.delete()
#     with pytest.raises(IntegrityError):
#         db_connection.check_constraints()
#     child.parent = default_parent
#     child.save(clean_and_validate=False)
