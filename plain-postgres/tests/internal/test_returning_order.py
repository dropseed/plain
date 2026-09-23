"""RETURNING comes back in VALUES order, including under ON CONFLICT.

`bulk_create()` and `bulk_upsert()` both map returned rows onto the objects
they were given by position. That holds only because Postgres processes a
multi-row INSERT sequentially and emits one RETURNING row per VALUES row, in
order -- on the DO UPDATE path as much as the plain insert path.

Nothing in the SQL standard promises this, so it is pinned here rather than
assumed. If this test ever fails, both call sites are wrong together.
"""

import random

from app.examples.models.upsert import UpsertItem
from plain.postgres.db import get_connection

ROWS = 400


def _returned_keys(keys: list[str]) -> list[str]:
    """Insert `keys` in one ON CONFLICT statement, return the RETURNING order."""
    table = UpsertItem.model_options.db_table
    # Only the placeholder count is interpolated; every value is a parameter.
    placeholders = ", ".join(["(%s, %s)"] * len(keys))
    sql = (
        f"INSERT INTO {table} (key, value) VALUES {placeholders} "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value "
        "RETURNING key"
    )
    params = [param for key in keys for param in (key, 1)]
    with get_connection().cursor() as cursor:
        cursor.execute(sql, params)
        return [row[0] for row in cursor.fetchall()]


def test_returning_order_matches_values_order_under_on_conflict(db):
    # Seed every other key, so the batch is a shuffled mix of inserts and
    # conflicting updates -- the case where the order could plausibly diverge.
    for index in range(0, ROWS, 2):
        UpsertItem(key=f"k{index}", value=0).create()

    keys = [f"k{index}" for index in range(ROWS)]
    random.Random(0).shuffle(keys)

    assert _returned_keys(keys) == keys


def test_returning_order_matches_values_order_for_plain_inserts(db):
    keys = [f"k{index}" for index in range(ROWS)]
    random.Random(1).shuffle(keys)

    assert _returned_keys(keys) == keys
