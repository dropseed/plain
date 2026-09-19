"""Only real, caller-owned fields are constructor parameters.

Anything else -- a typo, a `ClassVar` accessor, the DB-owned primary key --
has to be an unknown argument, or the checker would bless a call the runtime
raises on.
"""

from __future__ import annotations

from app.examples.models.defaults import DefaultsExample
from app.examples.models.delete import DeleteParent
from app.examples.models.querysets import DefaultQuerySetModel


def must_reject_an_unknown_field_name() -> None:
    DefaultsExample(name="n", nope="x")  # ty: ignore[unknown-argument]


def must_reject_the_auto_primary_key() -> None:
    # Postgres owns `id`. Runtime half: tests/public/test_manual_pk.py.
    DefaultQuerySetModel(id=1, name="x")  # ty: ignore[unknown-argument]


def must_reject_an_explicit_none_primary_key() -> None:
    # Allowed at runtime (it is the field's own default) but still not a
    # constructor parameter as far as the checker is concerned.
    DefaultQuerySetModel(id=None, name="x")  # ty: ignore[unknown-argument]


def must_reject_a_classvar_accessor() -> None:
    # `query` and `model_options` are ClassVars precisely so they stay out of
    # the synthesized constructor.
    DeleteParent(name="n", query=None)  # ty: ignore[unknown-argument]


def must_reject_a_reverse_relation_accessor() -> None:
    # `childcascade_set` is a ClassVar ReverseForeignKey. A non-ClassVar one
    # would leak into the constructor -- that is what this pins.
    DeleteParent(name="n", childcascade_set=[])  # ty: ignore[unknown-argument]
