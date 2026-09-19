"""Reverse relations are class-level accessors, never constructor fields.

They are declared `ClassVar[types.ReverseForeignKey[...]]`, which keeps them
out of the synthesized constructor (see construction_unknown_kwargs.py) and
makes them read-only on an instance.
"""

from __future__ import annotations

from typing import Any, assert_type

from app.examples.models.delete import ChildCascade, DeleteParent
from plain.postgres.fields.related_managers import ReverseForeignKeyManager
from plain.postgres.query import QuerySet


def must_accept_instance_access_as_a_manager(parent: DeleteParent) -> None:
    assert_type(
        parent.childcascade_set,
        ReverseForeignKeyManager[ChildCascade, QuerySet[Any]],
    )


def must_reject_assigning_to_a_reverse_relation(parent: DeleteParent) -> None:
    # The descriptor has no `__set__`. Runtime half: tests/public/test_related.py.
    parent.childcascade_set = []  # ty: ignore[invalid-attribute-access]
