"""Typed `where()` clause backed by field-method conditions.

First slice of the typed query API: field descriptors expose `equals`,
`not_equal`, comparison and string lookup methods that return Q objects;
`QuerySet.where()` accepts them positionally.

The static half of the contract -- which calls the type checker must reject,
and what the descriptors must keep typing as -- lives in `tests/typing/`.
"""

from __future__ import annotations

import pytest
from app.examples.models.defaults import DefaultsExample
from app.examples.models.relationships import Widget
from app.examples.models.string_conditions import StringConditionsExample
from plain.postgres import Q


def test_field_methods_return_q_objects():
    """The methods are usable before any DB hit and produce Q objects."""
    assert isinstance(DefaultsExample.name.equals("foo"), Q)
    assert isinstance(DefaultsExample.priority.gte(5), Q)
    assert isinstance(DefaultsExample.name.contains("oo"), Q)
    assert isinstance(DefaultsExample.note.is_null(), Q)
    assert isinstance(DefaultsExample.priority.is_in([1, 2]), Q)


def test_where_filters_by_equals(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="bob")

    rows = list(DefaultsExample.query.where(DefaultsExample.name.equals("alice")))
    assert [r.name for r in rows] == ["alice"]


def test_where_ands_multiple_conditions(db):
    DefaultsExample.query.create(name="alice", priority=1)
    DefaultsExample.query.create(name="alice", priority=10)
    DefaultsExample.query.create(name="bob", priority=10)

    rows = list(
        DefaultsExample.query.where(
            DefaultsExample.name.equals("alice"),
            DefaultsExample.priority.gte(5),
        )
    )
    assert [(r.name, r.priority) for r in rows] == [("alice", 10)]


def test_where_combines_with_or(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="bob")
    DefaultsExample.query.create(name="carol")

    rows = list(
        DefaultsExample.query.where(
            DefaultsExample.name.equals("alice") | DefaultsExample.name.equals("carol")
        ).order_by("name")
    )
    assert [r.name for r in rows] == ["alice", "carol"]


def test_not_equal_filters_inverse(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="bob")

    rows = list(DefaultsExample.query.where(DefaultsExample.name.not_equal("alice")))
    assert [r.name for r in rows] == ["bob"]


def test_text_field_string_lookups(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="alpha")
    DefaultsExample.query.create(name="bob")

    starts = list(
        DefaultsExample.query.where(DefaultsExample.name.startswith("al")).order_by(
            "name"
        )
    )
    assert [r.name for r in starts] == ["alice", "alpha"]


def test_where_filters_by_is_in(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="bob")
    DefaultsExample.query.create(name="carol")

    rows = list(
        DefaultsExample.query.where(
            DefaultsExample.name.is_in(["alice", "carol"])
        ).order_by("name")
    )
    assert [r.name for r in rows] == ["alice", "carol"]


def test_is_in_negation_excludes_members(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="bob")
    DefaultsExample.query.create(name="carol")

    rows = list(
        DefaultsExample.query.where(
            ~DefaultsExample.name.is_in(["alice", "carol"])
        ).order_by("name")
    )
    assert [r.name for r in rows] == ["bob"]


def test_is_null_with_explicit_default(db):
    DefaultsExample.query.create(name="alice", note=None)
    DefaultsExample.query.create(name="bob")  # default "auto"

    nulls = list(DefaultsExample.query.where(DefaultsExample.note.is_null()))
    assert [r.name for r in nulls] == ["alice"]

    non_nulls = list(DefaultsExample.query.where(DefaultsExample.note.is_null(False)))
    assert [r.name for r in non_nulls] == ["bob"]


# ---------------------------------------------------------------------------
# Pattern conditions live on `Field`, restricted to string-valued fields by
# their `self` annotation. So they reach every string-valued field regardless
# of its base class — `GenericIPAddressField` is a DefaultableField and
# `RandomStringField` is a ColumnField, and neither inherits TextField.
# ---------------------------------------------------------------------------


def test_where_filters_ip_address_field_by_pattern(db):
    StringConditionsExample.query.create(label="private", ip="10.0.0.1")
    StringConditionsExample.query.create(label="local", ip="192.168.1.1")

    rows = list(
        StringConditionsExample.query.where(
            StringConditionsExample.ip.startswith("10.")
        )
    )
    assert [r.label for r in rows] == ["private"]


def test_where_filters_random_string_field_by_pattern(db):
    """The token is generated by Postgres, so read one back and match on it."""
    StringConditionsExample.query.create(label="only", ip="10.0.0.1")

    token = StringConditionsExample.query.get(label="only").token
    assert len(token) == 16

    rows = list(
        StringConditionsExample.query.where(
            StringConditionsExample.token.startswith(token[:4])
        )
    )
    assert [r.label for r in rows] == ["only"]


# ---------------------------------------------------------------------------
# None operands on ordering conditions.
#
# There is deliberately no static pin for this one in tests/typing/. On a
# nullable field `T` includes None, and None cannot be subtracted from a
# TypeVar: probed against ty 0.0.80 and pyright 1.1.414,
# `self: Field[X | None], value: X` selects the intended overload but solves X
# as `int | None`, so `.gte(None)` type-checks either way. The runtime refusal
# below is the guard.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["gt", "gte", "lt", "lte"])
def test_ordering_condition_rejects_none(method: str) -> None:
    with pytest.raises(TypeError, match=rf"\.{method}\(\) has no meaning for None"):
        getattr(DefaultsExample.note, method)(None)


def test_ordering_condition_still_accepts_a_value_on_a_nullable_field() -> None:
    assert DefaultsExample.note.gte("m").children == [("note__gte", "m")]


def test_is_null_and_equals_still_accept_none() -> None:
    """`equals(None)` is the ORM's exact-None rewrite and stays legal."""
    assert DefaultsExample.note.equals(None).children == [("note", None)]
    assert DefaultsExample.note.is_null().children == [("note__isnull", True)]


class TestConditionsBelongToTheirModel:
    """`Field[T]` carries no model identity, so nothing stops a condition built
    from one model's field being handed to another model's `where()`. The
    lookup name then resolves against the queried model -- silently the wrong
    column when both models have one by that name. `where()` rejects it.

    `Widget` is the other model here because it also has a `name`, which is
    exactly the case that used to pass silently.
    """

    def test_same_model_condition_passes(self, db):
        DefaultsExample.query.create(name="alice")
        rows = DefaultsExample.query.where(DefaultsExample.name.equals("alice"))
        assert [r.name for r in rows] == ["alice"]

    def test_other_model_condition_raises_although_the_column_exists(self, db):
        """The dangerous case: both models have a `name`, so without the check
        this quietly filtered DefaultsExample.name and returned rows."""
        DefaultsExample.query.create(name="alice")
        with pytest.raises(TypeError) as excinfo:
            DefaultsExample.query.where(Widget.name.equals("alice"))
        message = str(excinfo.value)
        assert "Widget.name" in message
        assert "DefaultsExample queryset" in message

    def test_other_model_condition_raises_when_the_column_does_not_exist(self, db):
        """Previously a FieldError from deep in the compiler."""
        with pytest.raises(TypeError, match="Widget.size"):
            DefaultsExample.query.where(Widget.size.equals("big"))

    def test_negated_condition_is_checked(self, db):
        """`not_equal` returns `~q`, which rebuilds the Q through copy()."""
        with pytest.raises(TypeError, match="Widget.name"):
            DefaultsExample.query.where(Widget.name.not_equal("x"))

    def test_combined_condition_is_checked(self, db):
        """`&` and `|` build a new Q; the sources of both sides travel with it."""
        good = DefaultsExample.name.equals("alice")
        bad = Widget.name.equals("alice")
        with pytest.raises(TypeError, match="Widget.name"):
            DefaultsExample.query.where(good & bad)
        with pytest.raises(TypeError, match="Widget.name"):
            DefaultsExample.query.where(good | bad)
        with pytest.raises(TypeError, match="Widget.name"):
            DefaultsExample.query.where(~(good & bad))

    def test_all_same_model_conditions_still_combine(self, db):
        DefaultsExample.query.create(name="alice", priority=3)
        DefaultsExample.query.create(name="bob", priority=1)
        rows = DefaultsExample.query.where(
            DefaultsExample.name.equals("alice") & DefaultsExample.priority.gte(2)
        )
        assert [r.name for r in rows] == ["alice"]

    def test_hand_written_q_is_not_checked(self, db):
        """A bare Q is filter()'s untyped spelling and names no source model,
        so where() leaves it alone rather than guessing."""
        DefaultsExample.query.create(name="alice")
        rows = DefaultsExample.query.where(Q(name="alice"))
        assert [r.name for r in rows] == ["alice"]

    def test_filter_is_unaffected(self, db):
        """The check is where()'s; filter() keeps taking anything."""
        DefaultsExample.query.create(name="alice")
        assert DefaultsExample.query.filter(name="alice").count() == 1
