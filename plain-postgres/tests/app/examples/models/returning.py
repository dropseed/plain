"""Test fixtures for QuerySet.returning() on update()/delete()."""

from __future__ import annotations

from typing import Any

from plain import postgres
from plain.postgres import types


@postgres.register_model
class ReturningEvent(postgres.Model):
    label = types.TextField(max_length=100)
    count = types.IntegerField(default=0)
    payload: dict[str, Any] | None = types.JSONField(required=False, allow_null=True)

    query: postgres.QuerySet[ReturningEvent] = postgres.QuerySet()


@postgres.register_model
class ReturningParent(postgres.Model):
    name = types.TextField(max_length=100)

    query: postgres.QuerySet[ReturningParent] = postgres.QuerySet()

    children: types.ReverseForeignKey[ReturningChild] = types.ReverseForeignKey(
        to="ReturningChild", field="parent"
    )


@postgres.register_model
class ReturningChild(postgres.Model):
    parent = types.ForeignKeyField(ReturningParent, on_delete=postgres.CASCADE)

    query: postgres.QuerySet[ReturningChild] = postgres.QuerySet()
