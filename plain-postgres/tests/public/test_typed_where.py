"""Typed `where()` clause backed by field-method conditions.

First slice of the typed query API: field descriptors expose `equals`,
`not_equal`, comparison and string lookup methods that return Q objects;
`QuerySet.where()` accepts them positionally.
"""

from __future__ import annotations

from typing import assert_type

from app.examples.models.defaults import DefaultsExample

from plain.postgres.fields.numeric import IntegerField
from plain.postgres.fields.text import TextField
from plain.postgres.query_utils import Q


def test_class_access_yields_typed_descriptors() -> None:
    """Class-level field access returns the descriptor, parameterized by T.

    These `assert_type` calls are checked by the type checker, not at runtime
    — but the function still has to import cleanly.
    """
    assert_type(DefaultsExample.name, TextField[str])
    assert_type(DefaultsExample.note, TextField[str | None])
    assert_type(DefaultsExample.priority, IntegerField[int])


def test_instance_access_yields_value_type() -> None:
    """Instance access returns the value type T (with nullability preserved)."""
    row = DefaultsExample(name="x", note=None, priority=1)
    assert_type(row.name, str)
    assert_type(row.note, str | None)
    assert_type(row.priority, int)


def test_field_methods_return_q_objects():
    """The methods are usable before any DB hit and produce Q objects."""
    assert isinstance(DefaultsExample.name.equals("foo"), Q)
    assert isinstance(DefaultsExample.priority.gte(5), Q)
    assert isinstance(DefaultsExample.name.contains("oo"), Q)
    assert isinstance(DefaultsExample.note.is_null(), Q)


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


def test_is_null_with_explicit_default(db):
    DefaultsExample.query.create(name="alice", note=None)
    DefaultsExample.query.create(name="bob")  # default "auto"

    nulls = list(DefaultsExample.query.where(DefaultsExample.note.is_null()))
    assert [r.name for r in nulls] == ["alice"]

    non_nulls = list(DefaultsExample.query.where(DefaultsExample.note.is_null(False)))
    assert [r.name for r in non_nulls] == ["bob"]
