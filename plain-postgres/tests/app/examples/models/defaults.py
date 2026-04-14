from __future__ import annotations

import uuid

from plain import postgres
from plain.postgres import types


@postgres.register_model
class DefaultsExample(postgres.Model):
    """Model for pinning current `default=` behavior before fields-db-defaults Phase 1."""

    name: str = types.TextField(max_length=100)
    # Callable default (evaluated in Python per instance)
    token_uuid: uuid.UUID = types.UUIDField(default=uuid.uuid4)
    # Static string default
    status: str = types.TextField(max_length=20, default="pending")
    # Static int default
    priority: int = types.IntegerField(default=5)
    # Nullable with a non-null default — for testing explicit-None override
    note: str | None = types.TextField(
        max_length=100, default="auto", allow_null=True, required=False
    )

    query: postgres.QuerySet[DefaultsExample] = postgres.QuerySet()
