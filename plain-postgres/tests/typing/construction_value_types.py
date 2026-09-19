"""The synthesized constructor is typed by each field's value type."""

from __future__ import annotations

from datetime import datetime

from app.examples.models.defaults import DefaultsExample
from app.examples.models.delete import ChildCascade, DeleteParent


def must_reject_wrong_value_type() -> None:
    DefaultsExample(name=123)  # ty: ignore[invalid-argument-type]


def must_reject_none_for_a_non_nullable_field() -> None:
    DefaultsExample(name=None)  # ty: ignore[invalid-argument-type]


def must_reject_wrong_type_for_a_nullable_field() -> None:
    # `note` is `Field[str | None]`: None is fine, an int is not.
    DefaultsExample(name="n", note=1)  # ty: ignore[invalid-argument-type]


def must_reject_wrong_model_for_a_foreign_key(when: datetime) -> None:
    ChildCascade(parent=when)  # ty: ignore[invalid-argument-type]


def must_reject_a_bare_pk_for_a_foreign_key() -> None:
    # The runtime descriptor accepts a bare PK on *assignment*; the
    # constructor is typed by the field's value type, so it does not.
    # Runtime half: tests/internal/test_fk_characterization.py.
    ChildCascade(parent=1)  # ty: ignore[invalid-argument-type]


def must_accept_the_declared_value_types(parent: DeleteParent) -> None:
    DefaultsExample(name="n", status="s", priority=1, note="x")
    DefaultsExample(name="n", note=None)
    ChildCascade(parent=parent)
