"""The cardinality terminals take conditions, and `get()` takes a key.

`get()`/`get_or_none()` have three entry points -- no arguments, typed
conditions, a primary key -- and each has to keep its return type. `first()`
and `last()` take conditions only; a bare int there would read as a count.

Runtime half: tests/public/test_typed_get.py.
"""

from typing import Never, assert_type

from app.examples.models.defaults import DefaultsExample
from app.examples.models.relationships import Tag


def must_accept_a_primary_key() -> None:
    assert_type(DefaultsExample.query.get(5), DefaultsExample)
    assert_type(DefaultsExample.query.get_or_none(5), DefaultsExample | None)


def must_reject_a_primary_key_that_is_not_the_key_type() -> None:
    # `Model.id` is a PrimaryKeyField, so the key is an int. A string from a
    # URL segment or CLI argument is parsed by the caller.
    DefaultsExample.query.get("5")  # ty: ignore[no-matching-overload]


def must_accept_conditions() -> None:
    assert_type(
        DefaultsExample.query.get(DefaultsExample.name.equals("a")), DefaultsExample
    )
    assert_type(
        DefaultsExample.query.get(
            DefaultsExample.name.equals("a"), DefaultsExample.priority.gte(5)
        ),
        DefaultsExample,
    )
    assert_type(
        DefaultsExample.query.get_or_none(DefaultsExample.name.equals("a")),
        DefaultsExample | None,
    )
    assert_type(
        DefaultsExample.query.first(DefaultsExample.name.equals("a")),
        DefaultsExample | None,
    )
    assert_type(
        DefaultsExample.query.last(DefaultsExample.name.equals("a")),
        DefaultsExample | None,
    )


def must_accept_the_bare_terminals() -> None:
    built = DefaultsExample.query.where(DefaultsExample.name.equals("a"))
    assert_type(built.get(), DefaultsExample)
    assert_type(built.get_or_none(), DefaultsExample | None)
    assert_type(built.first(), DefaultsExample | None)


def must_accept_the_keyword_form() -> None:
    """`filter()`'s untyped spelling is unchanged."""
    assert_type(DefaultsExample.query.get(name="a"), DefaultsExample)
    assert_type(DefaultsExample.query.get(id=5), DefaultsExample)


def must_reject_a_primary_key_on_first_and_last() -> None:
    DefaultsExample.query.first(5)  # ty: ignore[invalid-argument-type]
    DefaultsExample.query.last(5)  # ty: ignore[invalid-argument-type]


def cross_model_conditions_are_a_runtime_refusal() -> None:
    """The checker can't see this one -- `Field[str]` carries no model.

    Runtime half: tests/public/test_typed_get.py::
    test_cross_model_condition_is_refused.
    """
    DefaultsExample.query.get(Tag.name.equals("x"))


def must_reject_the_primary_key_form_on_a_row_queryset() -> None:
    """A row has no key of its own, and `rows[5]` is already the sixth row.

    The call isn't a type error -- narrowing the parameter would break the
    override -- but `Never` says it doesn't return, so a caller's trailing
    code reads as unreachable. Which is why this claim gets a function of
    its own: anything written after it would be unreachable too, and an
    unreachable `assert_type` pins nothing. Runtime half:
    tests/public/test_typed_get.py.
    """
    rows = DefaultsExample.query.select(DefaultsExample.name, flat=True)
    assert_type(rows.get(5), Never)


def must_accept_conditions_on_a_row_queryset() -> None:
    rows = DefaultsExample.query.select(DefaultsExample.name, flat=True)
    assert_type(rows.get(DefaultsExample.name.equals("a")), str)
    assert_type(rows.get_or_none(DefaultsExample.name.equals("a")), str | None)
    assert_type(rows.first(DefaultsExample.name.equals("a")), str | None)
