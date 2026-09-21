"""Internals of the typed where() surface.

These reach past the documented API -- `CONDITION_METHODS`, `_model_meta`,
`Field.with_lookup_prefix` -- to pin the *mechanism* rather than the contract.
The contract lives in `tests/public/test_typed_where.py` and
`test_typed_where_fk.py`; if these fail and those don't, something shifted
under the hood and you get to decide whether it should have.
"""

from __future__ import annotations

import pytest
from app.examples.models.defaults import DefaultsExample
from app.examples.models.delete import ChildCascade, DeleteParent
from app.examples.models.encrypted import SecretStore
from app.examples.models.relationships import Widget, WidgetTag
from plain.postgres.expressions import F
from plain.postgres.fields.base import CONDITION_METHODS, STRING_CONDITION_LOOKUPS


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
        # field directly. This is exactly what RelatedFieldRef hands back --
        # including the source model, the root such a traversal would start
        # from.
        return SecretStore._model_meta.get_forward_field("api_key").with_lookup_prefix(
            "store", DefaultsExample
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
        RelatedFieldRef(
            model="Tag",  # ty: ignore[invalid-argument-type]
            prefix="tags",
            target_name="id",
            source_model=DefaultsExample,
        )

    # An AttributeError subclass, so the attribute protocol still holds.
    assert issubclass(UnresolvedRelationError, AttributeError)


def test_pattern_conditions_are_registered_on_every_field():
    """Why the string-only restriction has to be a *type* guard.

    `Contains` and friends are registered on `Field` itself (see lookups.py),
    so an IntegerField builds a perfectly valid `priority__contains` lookup
    that Postgres will run. Nothing at runtime distinguishes a string field
    from an int one, which is why the `self` annotation on the pattern
    conditions is the whole guard -- pinned from the checker's side in
    `tests/typing/conditions_value_types.py`.
    """
    assert DefaultsExample.priority.get_lookup("contains") is not None


def _compiled(queryset):
    """The SQL and params a queryset would send."""
    return queryset.sql_query.sql_with_params()


@pytest.mark.parametrize(("method", "lookup"), STRING_CONDITION_LOOKUPS.items())
def test_string_conditions_compile_like_their_filter_lookup(db, method, lookup):
    """Each string condition is the typed spelling of one `filter()` lookup,
    so the two have to compile to the same statement -- and the names don't
    all match (`iequals` builds `iexact`), which is what this pins."""
    typed = DefaultsExample.query.where(
        getattr(DefaultsExample.name, method)("alice"),
    )
    untyped = DefaultsExample.query.filter(**{f"name__{lookup}": "alice"})

    assert _compiled(typed) == _compiled(untyped)


class TestComparingAgainstAnotherColumn:
    """A `Field` on the right-hand side of a comparison is a column
    reference. `_build_q` turns it into the `F(...)` the ORM already
    understands, so the two spellings have to compile identically.

    Public half: tests/public/test_typed_where.py.
    """

    def test_compiles_like_the_f_expression(self, db):
        typed = DefaultsExample.query.where(
            DefaultsExample.priority.lt(DefaultsExample.id)
        )
        untyped = DefaultsExample.query.filter(priority__lt=F("id"))

        assert _compiled(typed) == _compiled(untyped)

    def test_a_traversed_column_keeps_its_relation_prefix(self, db):
        """A traversed field's `name` already carries the prefix, so both
        sides of the comparison name the joined column."""
        typed = WidgetTag.query.where(WidgetTag.widget.name.equals(WidgetTag.tag.name))
        untyped = WidgetTag.query.filter(widget__name=F("tag__name"))

        assert _compiled(typed) == _compiled(untyped)

    def test_a_right_hand_column_from_another_model_is_rejected(self, db):
        """The cross-model guard reads both sides -- a right-hand column from
        another model resolves against the queried model just as silently as a
        left-hand one would."""
        with pytest.raises(TypeError, match="Widget.size"):
            DefaultsExample.query.where(DefaultsExample.name.equals(Widget.size))

    def test_both_sides_are_recorded_as_origins(self):
        q = DefaultsExample.name.equals(Widget.size)
        assert q._condition_origins == frozenset(
            {(DefaultsExample, "name"), (Widget, "size")}
        )
