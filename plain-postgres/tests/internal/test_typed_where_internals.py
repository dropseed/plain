"""Internals of the typed where() surface.

These reach past the documented API -- `CONDITION_METHODS`, `_model_meta`,
`Field.with_lookup_prefix` -- to pin the *mechanism* rather than the contract.
The contract lives in `tests/public/test_typed_where.py` and
`test_typed_where_fk.py`; if these fail and those don't, something shifted
under the hood and you get to decide whether it should have.
"""

from __future__ import annotations

import pytest
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.encrypted import SecretStore
from plain.postgres.fields.base import CONDITION_METHODS


def test_traversal_hands_back_the_field_itself():
    """The traversed object is the related model's own field, renamed. That is
    what makes its surface identical to direct access by construction, rather
    than by a delegation list someone has to keep in sync."""
    direct = DeleteParent._model_meta.get_forward_field("name")
    traversed = ChildCascade.parent.name

    assert type(traversed) is type(direct)
    assert traversed.name == "parent__name"
    assert direct.name == "name"  # the original is untouched


@pytest.mark.parametrize("method", CONDITION_METHODS)
def test_every_condition_name_gets_the_relation_advice(method):
    """Sweep the whole condition surface, so a method added later can't quietly
    fall through to the generic "not a traversable field" message."""
    with pytest.raises(AttributeError) as excinfo:
        getattr(ChildCascade.parent, method)

    message = str(excinfo.value)
    assert "is a relation, not a field" in message
    assert f"parent.id.{method}(...)" in message


class TestEncryptedFieldTraversalBlocked:
    """An encrypted field's refusals travel with it, because traversal hands
    back the field itself. The message names the full path, since the prefixed
    copy carries it as its name."""

    @pytest.fixture
    def traversed(self):
        # No model in the examples app has an FK to SecretStore, so prefix the
        # field directly. This is exactly what RelatedFieldRef hands back.
        return SecretStore._model_meta.get_forward_field("api_key").with_lookup_prefix(
            "store"
        )

    @pytest.mark.parametrize("method", [m for m in CONDITION_METHODS if m != "is_null"])
    def test_traversed_condition_raises(self, traversed, method):
        with pytest.raises(
            TypeError, match=rf"store__api_key.*does not support \.{method}\("
        ):
            getattr(traversed, method)("x")

    def test_traversed_is_null_still_works(self, traversed):
        assert traversed.is_null().children == [("store__api_key__isnull", True)]


def test_traversal_before_the_target_resolves_says_so():
    """A relation's target is a string until the model registers. A traversal
    that runs at import time can land here first, and the old code dereferenced
    `str._model_meta` -- an AttributeError that `hasattr` then swallowed, so
    the symptom was a missing attribute rather than a timing problem."""
    from plain.postgres.fields.related_typed import (
        RelatedFieldRef,
        UnresolvedRelationError,
    )

    with pytest.raises(UnresolvedRelationError, match=r"'Tag' hasn't been resolved"):
        RelatedFieldRef(model="Tag", prefix="tags", target_name="id")  # ty: ignore[invalid-argument-type]

    # An AttributeError subclass, so the attribute protocol still holds.
    assert issubclass(UnresolvedRelationError, AttributeError)
