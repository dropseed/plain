"""Test fixtures for QuerySet.returning() on update()/delete()."""

from __future__ import annotations

from typing import Any

from plain.postgres import types

from plain import postgres


@postgres.register_model
class ReturningEvent(postgres.Model):
    label = types.TextField(max_length=100)
    count = types.IntegerField(default=0)
    payload: dict[str, Any] | None = types.JSONField(required=False, allow_null=True)

    query: postgres.QuerySet[ReturningEvent] = postgres.QuerySet()
