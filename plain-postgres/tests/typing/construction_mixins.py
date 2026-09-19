"""Mixins that declare fields must inherit `postgres.ModelMixin`.

PEP 681 only collects synthesized parameters from bases that carry the
transform themselves. A plain mixin's fields are invisible to the checker even
though the runtime collects them off the MRO, so valid code gets rejected --
loudly, here, rather than in someone's app.

Runtime half: tests/internal/test_typed_construction_preflight.py, which runs
`CheckTypedConstruction` over the live registry.
"""

from __future__ import annotations

from plain.postgres import Field, ModelMixin, types
from plain.postgres.base import Model


class PlainMixin:
    shared: Field[str] = types.TextField(max_length=10)


class UsesPlainMixin(PlainMixin, Model):
    name: Field[str] = types.TextField(max_length=10)


class TransformedMixin(ModelMixin):
    shared: Field[str] = types.TextField(max_length=10)


class UsesModelMixin(TransformedMixin, Model):
    name: Field[str] = types.TextField(max_length=10)


def must_reject_a_field_from_a_transformless_mixin() -> None:
    UsesPlainMixin(name="n", shared="s")  # ty: ignore[unknown-argument]


def must_accept_a_field_from_a_model_mixin() -> None:
    UsesModelMixin(name="n", shared="s")
