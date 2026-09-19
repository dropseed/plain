"""Typed `where()` clause backed by field-method conditions.

First slice of the typed query API: field descriptors expose `equals`,
`not_equal`, comparison and string lookup methods that return Q objects;
`QuerySet.where()` accepts them positionally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_type

from app.examples.models.defaults import DefaultsExample
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
