"""Condition methods are typed by the field's value type.

`equals`/`is_in`/the ordering comparisons take T. The pattern conditions live
on `Field` like everything else -- they have to, because `Field[T]` is the
annotation models carry -- and are restricted to string-valued fields by their
`self` annotation.

That restriction is type-only on purpose: `Contains` and friends are
registered on `Field` itself, so `IntegerField.contains("9")` builds a lookup
Postgres will happily run. The checker is the whole guard, which is why these
claims have no runtime counterpart.
"""

from __future__ import annotations

from typing import assert_type

from app.examples.models.defaults import DefaultsExample
from app.examples.models.string_conditions import StringConditionsExample
from plain.postgres.expressions import F
from plain.postgres.query_utils import Q


def must_accept_conditions_on_the_matching_value_type() -> None:
    assert_type(DefaultsExample.name.equals("a"), Q)
    assert_type(DefaultsExample.priority.gte(5), Q)
    assert_type(DefaultsExample.priority.is_in([1, 2, 3]), Q)
    assert_type(DefaultsExample.name.is_in(["a", "b"]), Q)
    assert_type(DefaultsExample.note.is_null(), Q)


def must_reject_a_wrong_element_type_in_is_in() -> None:
    DefaultsExample.priority.is_in(["no", "ints"])  # ty: ignore[invalid-argument-type]


def must_reject_a_wrong_operand_type() -> None:
    DefaultsExample.priority.equals("five")  # ty: ignore[invalid-argument-type]
    DefaultsExample.name.gte(5)  # ty: ignore[invalid-argument-type]


def must_accept_pattern_conditions_on_string_fields() -> None:
    assert_type(DefaultsExample.name.startswith("a"), Q)
    assert_type(DefaultsExample.note.contains("a"), Q)
    # Neither of these inherits TextField -- GenericIPAddressField is a
    # DefaultableField and RandomStringField is a ColumnField -- so this is
    # also what pins the conditions to `Field` rather than to TextField.
    assert_type(StringConditionsExample.ip.startswith("10."), Q)
    assert_type(StringConditionsExample.token.startswith("ab"), Q)


def must_reject_pattern_conditions_on_a_non_string_field() -> None:
    DefaultsExample.priority.startswith("a")  # ty: ignore[invalid-argument-type]
    DefaultsExample.priority.contains("a")  # ty: ignore[invalid-argument-type]
    DefaultsExample.priority.icontains("a")  # ty: ignore[invalid-argument-type]
    DefaultsExample.priority.endswith("a")  # ty: ignore[invalid-argument-type]
    DefaultsExample.priority.iequals("a")  # ty: ignore[invalid-argument-type]
    DefaultsExample.priority.istartswith("a")  # ty: ignore[invalid-argument-type]
    DefaultsExample.priority.iendswith("a")  # ty: ignore[invalid-argument-type]


def must_accept_case_insensitive_conditions_on_string_fields() -> None:
    assert_type(DefaultsExample.name.iequals("a"), Q)
    assert_type(DefaultsExample.name.istartswith("a"), Q)
    assert_type(DefaultsExample.name.iendswith("a"), Q)
    assert_type(DefaultsExample.note.iequals("a"), Q)
    assert_type(StringConditionsExample.ip.istartswith("10."), Q)


def must_accept_a_condition_from_another_model_because_the_checker_cannot_see_it() -> (
    None
):
    """A condition carries its value type but not its *model*.

    `Field[str]` is `Field[str]` whichever model declared it, so nothing here
    distinguishes a condition meant for `DefaultsExample.query.where()` from
    one meant for `StringConditionsExample.query.where()`. This line has to
    type-check clean -- that is the whole reason `where()` carries a runtime
    check instead.

    If a future `Field` ever carries model identity, this line starts erroring
    and the runtime check can be reconsidered. Runtime half:
    tests/public/test_typed_where.py::TestConditionsBelongToTheirModel.
    """
    assert_type(StringConditionsExample.label.equals("a"), Q)
    DefaultsExample.query.where(StringConditionsExample.label.equals("a"))


def must_accept_a_column_of_the_same_value_type() -> None:
    """Comparing two columns. Runtime half:
    tests/internal/test_typed_where_internals.py."""
    assert_type(DefaultsExample.priority.lt(DefaultsExample.priority), Q)
    assert_type(DefaultsExample.name.equals(DefaultsExample.name), Q)


def must_reject_a_column_of_another_value_type() -> None:
    DefaultsExample.priority.lt(DefaultsExample.name)  # ty: ignore[invalid-argument-type]


def must_accept_a_nullable_column_on_the_right_of_a_non_null_one() -> None:
    """`Field` is invariant in `T`, so `Field[str | None]` is not a
    `Field[str]`. The `Field[T | None]` arm is what lets a non-null column
    compare against a nullable one."""
    assert_type(DefaultsExample.name.equals(DefaultsExample.note), Q)


def must_reject_a_non_null_column_on_the_right_of_a_nullable_one() -> None:
    """The direction that isn't expressible: from `Field[str | None]` there
    is no way to name `str` without its `None`, so the `Field[T]` arm solves
    to `Field[str | None]` and a plain `Field[str]` misses it. Compare the
    other way round, or use `filter(note=F("name"))`."""
    DefaultsExample.note.equals(DefaultsExample.name)  # ty: ignore[invalid-argument-type]


def must_accept_an_expression_of_any_output_type() -> None:
    """The `Combinable` arm is untyped on purpose -- an expression's output
    type isn't tracked, so this int column happily takes an `F()` naming a
    text one. `F()` is `filter()`'s escape hatch and behaves like it."""
    assert_type(DefaultsExample.priority.lt(F("name")), Q)
