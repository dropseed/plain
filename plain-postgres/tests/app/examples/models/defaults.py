from __future__ import annotations

import uuid
from datetime import datetime

from plain import postgres
from plain.postgres import types
from plain.postgres.functions import GenRandomUUID, Now


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


@postgres.register_model
class DBDefaultsExample(postgres.Model):
    """Model exercising DB-expression defaults (fields-db-defaults Phase 1)."""

    name: str = types.TextField(max_length=100)
    # Expression default — rendered as `DEFAULT gen_random_uuid()` in DDL
    db_uuid: uuid.UUID = types.UUIDField(default=GenRandomUUID())
    # Expression default — rendered as `DEFAULT STATEMENT_TIMESTAMP()` in DDL
    created_at: datetime = types.DateTimeField(default=Now())

    query: postgres.QuerySet[DBDefaultsExample] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            # Constraint over an expression-default field — exercises the
            # "validate_constraints must skip DATABASE_DEFAULT" path.
            postgres.UniqueConstraint(
                fields=["db_uuid"], name="dbdefaultsexample_db_uuid_unique"
            ),
        ],
    )
