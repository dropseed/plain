"""Tests for `ForeignKeyField._check_required_cycle` — the preflight that
catches foreign key cycles where every edge is required.

Foreign keys are NOT DEFERRABLE, so each one is checked at the INSERT that
would violate it. When every edge of a cycle is `allow_null=False`, there is
no order that gets the first row in — the shape is permanently
un-insertable, inside a transaction or not.

Models here are defined against an isolated `ModelsRegistry` so they never
reach the real one.
"""

from __future__ import annotations

from plain.postgres import types
from plain.postgres.fields.related import ForeignKeyField
from plain.postgres.meta import Meta
from plain.postgres.registry import ModelsRegistry

from plain import postgres

CYCLE_ID = "fields.foreign_key_required_cycle"

_registry = ModelsRegistry()
_registry.ready = True


@postgres.register_model
class Invoice(postgres.Model):
    current_version = types.ForeignKeyField(
        "InvoiceVersion",
        on_delete=postgres.CASCADE,
    )

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class InvoiceVersion(postgres.Model):
    invoice = types.ForeignKeyField(Invoice, on_delete=postgres.CASCADE)

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class Order(postgres.Model):
    """Nullable back-reference — the supported way to express a cycle."""

    current_line = types.ForeignKeyField(
        "OrderLine",
        on_delete=postgres.CASCADE,
        allow_null=True,
        required=False,
    )

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class OrderLine(postgres.Model):
    order = types.ForeignKeyField(Order, on_delete=postgres.CASCADE)

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class Node(postgres.Model):
    """One-edge cycle: the first row has nothing to point at."""

    parent = types.ForeignKeyField("self", on_delete=postgres.CASCADE)

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class Alpha(postgres.Model):
    beta = types.ForeignKeyField("Beta", on_delete=postgres.CASCADE)

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class Beta(postgres.Model):
    gamma = types.ForeignKeyField("Gamma", on_delete=postgres.CASCADE)

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class Gamma(postgres.Model):
    alpha = types.ForeignKeyField(Alpha, on_delete=postgres.CASCADE)

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class Country(postgres.Model):
    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class City(postgres.Model):
    country = types.ForeignKeyField(Country, on_delete=postgres.CASCADE)

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


@postgres.register_model
class Address(postgres.Model):
    city = types.ForeignKeyField(City, on_delete=postgres.CASCADE)

    _model_meta = Meta(models_registry=_registry)
    model_options = postgres.Options(package_label="fkcycle")


def _cycle_results(model: type[postgres.Model], field_name: str) -> list:
    field = model._model_meta.get_field(field_name)
    assert isinstance(field, ForeignKeyField)
    return [r for r in field.preflight() if r.id == CYCLE_ID]


def test_two_required_foreign_keys_pointing_at_each_other():
    """Reported once, from the first-sorting edge of the cycle."""
    results = _cycle_results(Invoice, "current_version")
    assert len(results) == 1
    assert (
        "fkcycle.Invoice.current_version → fkcycle.InvoiceVersion.invoice "
        "→ fkcycle.Invoice" in results[0].fix
    )

    # The other edge of the same cycle stays quiet.
    assert _cycle_results(InvoiceVersion, "invoice") == []


def test_nullable_edge_breaks_the_cycle():
    assert _cycle_results(Order, "current_line") == []
    assert _cycle_results(OrderLine, "order") == []


def test_required_self_foreign_key():
    results = _cycle_results(Node, "parent")
    assert len(results) == 1
    assert "fkcycle.Node.parent → fkcycle.Node" in results[0].fix


def test_three_model_cycle_names_every_edge():
    results = _cycle_results(Alpha, "beta")
    assert len(results) == 1
    assert (
        "fkcycle.Alpha.beta → fkcycle.Beta.gamma → fkcycle.Gamma.alpha "
        "→ fkcycle.Alpha" in results[0].fix
    )

    assert _cycle_results(Beta, "gamma") == []
    assert _cycle_results(Gamma, "alpha") == []


def test_chain_without_a_cycle():
    assert _cycle_results(Address, "city") == []
    assert _cycle_results(City, "country") == []


def test_nullable_circular_example_models():
    """CircA/CircB in the example app point at each other, but both edges are
    nullable — a legitimate cycle that must not be flagged."""
    from app.examples.models.delete import CircA, CircB

    assert _cycle_results(CircA, "partner") == []
    assert _cycle_results(CircB, "partner") == []
