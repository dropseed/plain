from __future__ import annotations

from plain.postgres.expressions import DatabaseDefaultExpression, Func
from plain.postgres.fields import UUIDField


class GenRandomUUID(DatabaseDefaultExpression, Func):
    template = "gen_random_uuid()"
    output_field = UUIDField()
