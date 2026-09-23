"""Typed entry points on the cardinality terminals.

`get()`, `get_or_none()`, `first()` and `last()` take the same conditions
`where()` does, and `get()`/`get_or_none()` additionally take a bare primary
key. All three spellings end in the terminal's own contract, unchanged.

The static half -- which of these calls the checker must reject -- lives in
`tests/typing/conditions_terminals.py`. The SQL identity claims are pinned in
`tests/internal/test_typed_get_sql.py`.
"""

import pytest
from app.examples.models.defaults import DefaultsExample
from app.examples.models.relationships import Tag


def test_get_by_primary_key(db):
    row = DefaultsExample.query.create(name="alice")

    assert DefaultsExample.query.get(row.id).id == row.id


def test_get_by_primary_key_missing_row(db):
    with pytest.raises(DefaultsExample.DoesNotExist):
        DefaultsExample.query.get(9_999_999)


def test_get_by_condition(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="bob")

    assert DefaultsExample.query.get(DefaultsExample.name.equals("alice")).name == (
        "alice"
    )


def test_get_ands_multiple_conditions(db):
    DefaultsExample.query.create(name="alice", priority=1)
    DefaultsExample.query.create(name="alice", priority=10)

    row = DefaultsExample.query.get(
        DefaultsExample.name.equals("alice"),
        DefaultsExample.priority.gte(5),
    )
    assert row.priority == 10


def test_get_with_conditions_still_asserts_one_row(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="alice")

    with pytest.raises(DefaultsExample.MultipleObjectsReturned):
        DefaultsExample.query.get(DefaultsExample.name.equals("alice"))


def test_get_on_a_built_query_is_unchanged(db):
    DefaultsExample.query.create(name="alice")

    built = DefaultsExample.query.where(DefaultsExample.name.equals("alice"))
    assert built.get().name == "alice"


def test_get_keyword_form_still_works(db):
    row = DefaultsExample.query.create(name="alice")

    assert DefaultsExample.query.get(id=row.id).id == row.id
    assert DefaultsExample.query.get(name="alice").id == row.id


def test_get_or_none_returns_none_for_a_missing_key(db):
    assert DefaultsExample.query.get_or_none(9_999_999) is None


def test_get_or_none_returns_the_row(db):
    row = DefaultsExample.query.create(name="alice")

    by_key = DefaultsExample.query.get_or_none(row.id)
    by_condition = DefaultsExample.query.get_or_none(
        DefaultsExample.name.equals("alice")
    )
    assert by_key is not None
    assert by_key.id == row.id
    assert by_condition is not None
    assert by_condition.id == row.id


def test_get_or_none_still_raises_on_multiple(db):
    DefaultsExample.query.create(name="alice")
    DefaultsExample.query.create(name="alice")

    with pytest.raises(DefaultsExample.MultipleObjectsReturned):
        DefaultsExample.query.get_or_none(DefaultsExample.name.equals("alice"))


def test_first_and_last_take_conditions(db):
    DefaultsExample.query.create(name="alice", priority=1)
    DefaultsExample.query.create(name="alice", priority=10)
    DefaultsExample.query.create(name="bob", priority=99)

    ordered = DefaultsExample.query.order_by("priority")
    first = ordered.first(DefaultsExample.name.equals("alice"))
    last = ordered.last(DefaultsExample.name.equals("alice"))
    assert first is not None
    assert first.priority == 1
    assert last is not None
    assert last.priority == 10


def test_first_returns_none_when_nothing_matches(db):
    assert DefaultsExample.query.first(DefaultsExample.name.equals("nobody")) is None
    assert DefaultsExample.query.last(DefaultsExample.name.equals("nobody")) is None


def test_cross_model_condition_is_refused(db):
    """`where()`'s guard, reported under the terminal's own name."""
    with pytest.raises(TypeError, match=r"get\(\) got a condition built from Tag.name"):
        DefaultsExample.query.get(Tag.name.equals("x"))

    with pytest.raises(TypeError, match=r"first\(\) got a condition built from"):
        DefaultsExample.query.first(Tag.name.equals("x"))


def test_mixing_a_primary_key_with_conditions_is_refused(db):
    with pytest.raises(TypeError, match=r"single primary key or typed conditions"):
        DefaultsExample.query.get(5, DefaultsExample.name.equals("alice"))  # ty: ignore[invalid-argument-type]


def test_a_primary_key_alongside_keyword_lookups_is_refused(db):
    """A key is the whole lookup -- `get(5, id=5)` would AND it with itself."""
    with pytest.raises(TypeError, match=r"also got keyword lookups"):
        DefaultsExample.query.get(5, id=5)  # ty: ignore[invalid-argument-type]

    with pytest.raises(TypeError, match=r"also got keyword lookups"):
        DefaultsExample.query.get_or_none(5, name="alice")  # ty: ignore[invalid-argument-type]


def test_conditions_alongside_keyword_lookups_still_work(db):
    """Conditions are `filter()` arguments, so they combine with its kwargs."""
    DefaultsExample.query.create(name="alice", priority=1)
    DefaultsExample.query.create(name="alice", priority=10)

    row = DefaultsExample.query.get(DefaultsExample.name.equals("alice"), priority=10)
    assert row.priority == 10


def test_a_non_condition_non_key_positional_is_refused(db):
    with pytest.raises(TypeError, match=r"DefaultsExample.id is an int"):
        DefaultsExample.query.get("5")  # ty: ignore[no-matching-overload]


def test_first_refuses_a_primary_key(db):
    with pytest.raises(TypeError, match=r"first\(\) takes typed conditions"):
        DefaultsExample.query.first(5)  # ty: ignore[invalid-argument-type]


def test_row_queryset_refuses_the_primary_key_form(db):
    DefaultsExample.query.create(name="alice")

    rows = DefaultsExample.query.select(DefaultsExample.name, flat=True)
    with pytest.raises(TypeError, match=r"Cannot call get\(primary_key\) after select"):
        rows.get(5)


def test_row_queryset_still_takes_conditions(db):
    DefaultsExample.query.create(name="alice")

    rows = DefaultsExample.query.select(DefaultsExample.name, flat=True)
    assert rows.get(DefaultsExample.name.equals("alice")) == "alice"
