"""Psycopg adapter registration for Plain.

The `AdaptersMap` returned by `get_adapters_template()` is attached to every
psycopg connection we open (via `build_connection_params` in `sources.py`).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from psycopg import adapt, adapters
from psycopg.abc import PyFormat
from psycopg.postgres import types as pg_types
from psycopg.types.range import BaseRangeDumper, Range, RangeDumper
from psycopg.types.string import TextLoader

TSRANGE_OID = pg_types["tsrange"].oid
TSTZRANGE_OID = pg_types["tstzrange"].oid


class PlainRangeDumper(RangeDumper):
    """A Range dumper customized for Plain."""

    def upgrade(self, obj: Range[Any], format: PyFormat) -> BaseRangeDumper:
        dumper = super().upgrade(obj, format)
        if dumper is not self and dumper.oid == TSRANGE_OID:
            dumper.oid = TSTZRANGE_OID
        return dumper


@lru_cache
def get_adapters_template() -> adapt.AdaptersMap:
    ctx = adapt.AdaptersMap(adapters)
    # No-op JSON loader to avoid psycopg3 round trips
    ctx.register_loader("jsonb", TextLoader)
    # Treat inet/cidr as text
    ctx.register_loader("inet", TextLoader)
    ctx.register_loader("cidr", TextLoader)
    ctx.register_dumper(Range, PlainRangeDumper)
    return ctx
