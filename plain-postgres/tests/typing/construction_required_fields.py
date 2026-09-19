"""A field with no call-site `default=` is a required constructor argument.

`@dataclass_transform` on `ModelBase` synthesizes the constructor from the
`Field[T]`-annotated attributes. Omittable means "its definition passed
`default=`" -- that is the PEP 681 rule, and it is not nullable-specific.
"""

from __future__ import annotations

from app.examples.models.defaults import DefaultsExample
from app.examples.models.delete import ChildCascade, DeleteParent


def must_reject_missing_required_field() -> None:
    # `name` has no default.
    DefaultsExample()  # ty: ignore[missing-argument]


def must_reject_missing_foreign_key() -> None:
    # A non-nullable FK is required like any other field.
    ChildCascade()  # ty: ignore[missing-argument]


def must_accept_fields_that_carry_a_default() -> None:
    # `status`, `priority` and `note` all pass `default=`, so only `name` is
    # required. If any of them lost its default this call would start failing.
    DefaultsExample(name="n")


def must_accept_every_field_spelled_out() -> None:
    DefaultsExample(name="n", status="pending", priority=1, note=None)


def must_accept_db_owned_fields_being_excluded(parent: DeleteParent) -> None:
    # `id` is a PrimaryKeyField (init=False) and is never a parameter; the
    # rejection of passing one anyway lives in construction_unknown_kwargs.py.
    ChildCascade(parent=parent)
