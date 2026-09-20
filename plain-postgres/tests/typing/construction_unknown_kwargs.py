"""Only real, caller-owned fields are constructor parameters.

Anything else -- a typo, a `ClassVar` accessor, the DB-owned primary key --
has to be an unknown argument, or the checker would bless a call the runtime
raises on.
"""

from __future__ import annotations

from app.examples.models.defaults import DefaultsExample
from app.examples.models.delete import DeleteParent
from app.examples.models.querysets import DefaultQuerySetModel
from plain.postgres import types
from plain.postgres.base import Model


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


class Unannotated(Model):
    """A model whose field carries no `Field[T]` annotation.

    `ModelBase` carries the transform, so the checker synthesizes *every*
    model's constructor from its annotated attributes alone. An unannotated
    field is not a parameter at all -- the runtime accepts
    `Unannotated(name="x")` and the checker can't. There is no opting out, so
    a type-checked app has to annotate every model.
    """

    name = types.TextField(max_length=10)


def must_reject_a_field_on_an_unannotated_model() -> None:
    Unannotated(name="x")  # ty: ignore[unknown-argument]
