"""Test fixtures for QuerySet.returning() on update()/delete()."""

from __future__ import annotations

from typing import Any

from plain.postgres import Field, types

from plain import postgres


@postgres.register_model
class ReturningEvent(postgres.Model):
    label: Field[str] = types.TextField(max_length=100)
    count: Field[int] = types.IntegerField(default=0)
    payload: Field[dict[str, Any] | None] = types.JSONField(
        required=False, allow_null=True, default=None
    )
