"""Class access on a foreign key yields the related model, not a descriptor.

`Field.__get__`'s first overload matches `Field[M] | Field[M | None]` where M
is a Model and returns `type[M]`. That one overload is what makes typed
traversal (`Child.parent.name.equals(...)`) type-check, and it has to cover
nullable and non-nullable foreign keys alike.

The cost of typing class access as the related model is that the relation
itself has no condition methods and no descriptor attributes -- which is also
the runtime behavior (`ForwardForeignKeyDescriptor.__getattr__` raises), so
the two agree. Runtime half: tests/public/test_typed_where_fk.py.
"""

from __future__ import annotations

from typing import assert_type

from app.examples.models.delete import (
    ChildCascade,
    ChildSetNull,
    DeleteParent,
    Grandchild,
)
from app.examples.models.relationships import WidgetTag
from plain.postgres.query_utils import Q


def must_accept_class_access_as_the_related_model() -> None:
    assert_type(ChildCascade.parent, type[DeleteParent])
    # Same overload, nullable side: `Field[DeleteParent | None]`.
    assert_type(ChildSetNull.parent, type[DeleteParent])


def must_accept_instance_access_as_the_value_type(
    child: ChildCascade, orphan: ChildSetNull
) -> None:
    assert_type(child.parent, DeleteParent)
    assert_type(orphan.parent, DeleteParent | None)


def must_accept_traversal_to_a_related_field() -> None:
    assert_type(ChildCascade.parent.name, type(DeleteParent.name))
    assert_type(ChildCascade.parent.name.equals("x"), Q)
    assert_type(ChildCascade.parent.name.startswith("x"), Q)
    assert_type(ChildCascade.parent.id.is_in([1, 2]), Q)
    # Nullable foreign keys traverse identically.
    assert_type(ChildSetNull.parent.id.is_null(), Q)


def must_accept_multi_hop_traversal() -> None:
    assert_type(Grandchild.mid_parent.grandparent.name.equals("x"), Q)


def must_accept_lookup_path_on_a_traversed_field() -> None:
    # `"parent__name"` at runtime; the claim here is only that it stays a
    # `str` after traversal, so generic code can build a lookup from it.
    # Runtime half: tests/public/test_typed_where_fk.py.
    assert_type(ChildCascade.parent.name.lookup_path, str)


def must_reject_a_condition_on_the_relation_itself() -> None:
    # The spelling that works is `parent.id.equals(...)`; a `.equals` on the
    # relation would have to mean something the lookup language cannot say.
    ChildCascade.parent.equals(1)  # ty: ignore[unresolved-attribute]


def must_reject_a_descriptor_attribute_on_the_relation() -> None:
    # `RelatedObjectDoesNotExist` still lives on the runtime descriptor, but
    # class access is typed as the related model. Catch `DeleteParent.
    # DoesNotExist` (or AttributeError) instead.
    _ = ChildCascade.parent.RelatedObjectDoesNotExist  # ty: ignore[unresolved-attribute]


def must_reject_an_unknown_related_field() -> None:
    _ = ChildCascade.parent.nonexistent_field  # ty: ignore[unresolved-attribute]


def must_reject_traversal_through_a_many_to_many() -> None:
    # Runtime-only hop. At the type level `tags` is `ManyToManyManager[Tag]`,
    # which exposes the manager API rather than Tag's fields -- typing it
    # would mean claiming `Widget.tags` itself yields `type[Tag]`, which is
    # false. Runtime half: tests/public/test_typed_where_fk.py.
    WidgetTag.widget.tags.name.equals("metal")  # ty: ignore[unresolved-attribute]
