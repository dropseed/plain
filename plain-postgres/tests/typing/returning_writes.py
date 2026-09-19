"""`returning()` pins what update()/delete() hand back.

Without it both writes are an int rowcount. The no-arg overload hydrates model
instances; the field-reference overload hands back dicts of just those columns.
The overload ladder is the whole promise, so it is asserted statically.
"""

from __future__ import annotations

from typing import Any, assert_type

from app.examples.models.delete import ChildCascade
from app.examples.models.returning import ReturningEvent


def must_accept_the_plain_writes() -> None:
    qs = ReturningEvent.query.filter(label="a")
    assert_type(qs.update(count=1), int)
    assert_type(qs.delete(), int)


def must_accept_no_arg_returning_as_instances() -> None:
    qs = ReturningEvent.query.filter(label="a")
    assert_type(qs.returning().update(count=1), list[ReturningEvent])
    assert_type(qs.returning().delete(), list[ReturningEvent])


def must_accept_field_returning_as_dicts() -> None:
    qs = ReturningEvent.query.filter(label="a")
    assert_type(qs.returning(ReturningEvent.id).update(count=1), list[dict[str, Any]])
    assert_type(qs.returning(ReturningEvent.id).delete(), list[dict[str, Any]])


def must_reject_string_field_names() -> None:
    # Runtime half: tests/public/test_returning.py::test_returning_string_arg_errors.
    ReturningEvent.query.returning("count")  # ty: ignore[invalid-argument-type]


def must_reject_a_relation_reference() -> None:
    # Model.fk is the relation descriptor, not a column.
    # Runtime half:
    # tests/public/test_returning.py::test_returning_relation_reference_errors.
    ChildCascade.query.returning(ChildCascade.parent)  # ty: ignore[invalid-argument-type]
