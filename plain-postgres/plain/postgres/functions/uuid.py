from __future__ import annotations

from plain.postgres.expressions import Func
from plain.postgres.fields import UUIDField


class GenRandomUUID(Func):
    template = "gen_random_uuid()"
    output_field = UUIDField()
