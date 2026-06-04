"""Timestamp invariants for the set-based write paths.

bulk_create fires pre_save (so updated_at's update_now bumps on its own) while
QuerySet.update() does not -- see core.py for why set_many stamps created_at and
touch stamps updated_at. These pin the observable invariants those choices buy.
"""

from __future__ import annotations

from datetime import timedelta

from plain.cache import cache
from plain.cache.models import CachedItem


def test_fresh_row_updated_not_before_created(db):
    cache.set("ts", "v")
    row = CachedItem.query.get(key="ts")
    assert row.updated_at >= row.created_at


def test_overwrite_preserves_created_and_advances_updated(db):
    cache.set("ts", "v1")
    created = CachedItem.query.get(key="ts").created_at

    cache.set("ts", "v2")
    row = CachedItem.query.get(key="ts")
    assert row.created_at == created  # creation time preserved on upsert
    assert row.updated_at >= created  # updated advanced


def test_set_many_upsert_preserves_created(db):
    cache.set_many({"a": 1, "b": 2})
    created = {k: CachedItem.query.get(key=k).created_at for k in ("a", "b")}

    cache.set_many({"a": 10, "b": 20})  # exercises the conflict path for both keys
    for k in ("a", "b"):
        row = CachedItem.query.get(key=k)
        assert row.created_at == created[k]  # preserved across the batch upsert
        assert row.updated_at >= row.created_at


def test_touch_advances_updated_at(db):
    cache.set("tch", "v")
    before = CachedItem.query.get(key="tch").updated_at

    cache.touch("tch", expiration=timedelta(days=1))
    after = CachedItem.query.get(key="tch").updated_at
    assert after > before  # touch must bump updated_at (QuerySet.update skips pre_save)
