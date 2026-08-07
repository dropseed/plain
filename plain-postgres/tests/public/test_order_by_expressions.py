from __future__ import annotations

from app.examples.models.iteration import IterationExample

from plain.postgres.expressions import F
from plain.postgres.functions import Lower


def test_order_by_f_expression(db):
    """`order_by()` accepts expressions, not just field-name strings."""
    IterationExample.query.create(name="beta", tag="b")
    IterationExample.query.create(name="alpha", tag="a")

    names = list(
        IterationExample.query.order_by(F("name")).values_list("name", flat=True)
    )

    assert names == ["alpha", "beta"]


def test_order_by_function_expression(db):
    """Database functions work as ordering expressions."""
    IterationExample.query.create(name="Beta", tag="b")
    IterationExample.query.create(name="alpha", tag="a")

    names = list(
        IterationExample.query.order_by(Lower("name")).values_list("name", flat=True)
    )

    assert names == ["alpha", "Beta"]
