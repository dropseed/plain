"""Typed `where()` clause backed by field-method conditions.

First slice of the typed query API: field descriptors expose `equals`,
`not_equal`, comparison and string lookup methods that return Q objects;
`QuerySet.where()` accepts them positionally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_type

import pytest
from app.examples.models.defaults import DefaultsExample
from app.examples.models.string_conditions import StringConditionsExample
from plain.postgres import Field
from plain.postgres.query_utils import Q


def test_class_access_yields_typed_descriptors() -> None:
    """Class-level field access returns the descriptor, parameterized by T.

    The declared type is what the checker sees — models annotate their fields
    `Field[T]`, so that (not the concrete `TextField[T]` the stub returns) is
    the type of a class-level access. `Field[T]` therefore has to carry the
    whole condition surface, including the string-only conditions, which it
    restricts to string-valued fields via the `self` annotation.

    These `assert_type` calls are checked by the type checker, not at runtime
    — but the function still has to import cleanly.
    """
    assert_type(DefaultsExample.name, Field[str])
    assert_type(DefaultsExample.note, Field[str | None])
    assert_type(DefaultsExample.priority, Field[int])


def test_instance_access_yields_value_type() -> None:
    """Instance access returns the value type T (with nullability preserved)."""
    row = DefaultsExample(name="x", note=None, priority=1)
    assert_type(row.name, str)
    assert_type(row.note, str | None)
    assert_type(row.priority, int)


def test_assignment_typing_accepts_value_type() -> None:
    """Assignment to a field instance accepts the declared value type."""
    row = DefaultsExample(name="x", note=None, priority=1)
    row.name = "y"  # str → str: OK
    row.priority = 99  # int → int: OK
    row.note = None  # None → str | None: OK (nullable)
    row.note = "set"  # str → str | None: OK


if TYPE_CHECKING:
    # Type-check only: these assignments must be flagged by ty. The ignore
    # markers are load-bearing — if Field.__set__ were typed loosely
    # (e.g. value: Any), ty would report them as unused suppressions.
    # Their presence here proves the type checker enforces T. We avoid
    # running the assignments at runtime because Field.__set__ also calls
    # to_python() which raises ValidationError on unconvertible input.
    def _typed_check_rejects_wrong_assignment() -> None:
        row = DefaultsExample(name="x", note=None, priority=1)
        row.name = 123  # ty: ignore[invalid-assignment]
        row.priority = "no"  # ty: ignore[invalid-assignment]
        # Non-nullable field rejects None at type-check time even though the
        # runtime would store it (and only fail later at validate/save).
        row.name = None  # ty: ignore[invalid-assignment]

    def _typed_check_is_in_element_type() -> None:
        # is_in takes an iterable of the field's value type. A matching
        # iterable type-checks clean; a wrong element type is flagged. The
        # ignore marker is load-bearing — if the parameter were typed loosely
        # (e.g. Iterable[Any]), ty would report it as an unused suppression.
        DefaultsExample.priority.is_in([1, 2, 3])
        DefaultsExample.name.is_in(["a", "b"])
        DefaultsExample.priority.is_in(["no", "ints"])  # ty: ignore[invalid-argument-type]

    def _typed_check_string_conditions_are_string_only() -> None:
        # The pattern conditions are declared on Field with a `self`
        # annotation that restricts them to string-valued fields, so they
        # survive the `Field[T]` annotation models carry without becoming
        # available on every field. The ignore marker is load-bearing — if the
        # restriction were dropped, ty would report it as unused. These stay
        # type-check-only because a non-text field has no such method at
        # runtime (AttributeError), which is what traversal reflects.
        DefaultsExample.name.startswith("a")
        DefaultsExample.note.contains("a")
        DefaultsExample.priority.startswith("a")  # ty: ignore[invalid-argument-type]
        DefaultsExample.priority.contains("a")  # ty: ignore[invalid-argument-type]
        DefaultsExample.priority.icontains("a")  # ty: ignore[invalid-argument-type]
        DefaultsExample.priority.endswith("a")  # ty: ignore[invalid-argument-type]


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


def test_pattern_condition_on_a_non_string_field_is_a_static_error() -> None:
    """The `self` annotation is the whole guard, and it is a static one — the
    load-bearing `ty: ignore` markers in the TYPE_CHECKING block above are what
    pin it.

    There is deliberately no runtime counterpart: `Contains`, `IContains`,
    `StartsWith` and `EndsWith` are registered on `Field` itself (see
    lookups.py), so every field has them and nothing at runtime distinguishes a
    string field from an int one. `IntegerField.contains("9")` builds a valid
    `priority__contains` lookup that Postgres will happily run. Same type-first
    guard model the encrypted fields use.
    """
    assert DefaultsExample.priority.get_lookup("contains") is not None


# ---------------------------------------------------------------------------
# None operands on ordering conditions.
#
# There is deliberately no static pin here. On a nullable field `T` includes
# None, and None cannot be subtracted from a TypeVar: probed against ty 0.0.80
# and pyright 1.1.414, `self: Field[X | None], value: X` selects the intended
# overload but solves X as `int | None`, so `.gte(None)` type-checks either
# way. The runtime refusal below is the guard.
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
