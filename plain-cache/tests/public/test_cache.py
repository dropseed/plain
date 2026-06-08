"""The cache contract: get/set/get_or_set, batch ops, touch, delete."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from plain.cache import cache
from plain.cache.models import CachedItem
from plain.utils import timezone


def test_get_set_delete(db):
    assert cache.get("k1") is None
    assert cache.get("k1", "fallback") == "fallback"

    cache.set("k1", "hello")
    assert cache.get("k1") == "hello"

    assert cache.delete("k1") is True
    assert cache.get("k1") is None
    assert cache.delete("k1") is False  # already gone


def test_set_stores_json_values(db):
    cache.set("k2", {"a": 1, "b": [2, 3]})
    assert cache.get("k2") == {"a": 1, "b": [2, 3]}


def test_set_overwrites_existing_key(db):
    cache.set("k-over", "old")
    cache.set("k-over", "new")
    assert cache.get("k-over") == "new"


def test_stored_none_is_a_hit(db):
    missing = object()
    cache.set("k-none", None)
    assert cache.get("k-none", "fallback") is None  # default not used -> it's a hit
    assert (
        cache.get("k-none", missing) is None
    )  # sentinel distinguishes hit from absent


def test_expired_entry_reads_as_absent(db):
    missing = object()
    cache.set("k-exp", "v", expiration=timedelta(seconds=-1))
    assert cache.get("k-exp") is None
    assert cache.get("k-exp", missing) is missing  # default returned -> truly absent


def test_set_defaults_to_never_expiring(db):
    cache.set("k-forever", "v")
    assert cache.get("k-forever") == "v"
    # No expiry set -> the row stores no expiration.
    assert CachedItem.query.get(key="k-forever").expires_at is None


def test_get_or_set_computes_only_on_miss(db):
    calls = []

    def compute():
        calls.append(1)
        return "computed"

    assert cache.get_or_set("k3", compute, expiration=timedelta(days=1)) == "computed"
    assert cache.get_or_set("k3", compute) == "computed"  # hit, not recomputed
    assert len(calls) == 1


def test_get_or_set_accepts_a_plain_value(db):
    assert cache.get_or_set("k4", "value") == "value"
    assert cache.get("k4") == "value"


def test_get_many_returns_only_live_entries(db):
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3, expiration=timedelta(seconds=-1))  # expired

    assert cache.get_many(["a", "b", "c", "missing"]) == {"a": 1, "b": 2}


def test_set_many_and_delete_many(db):
    cache.set_many({"x": 1, "y": 2, "z": 3})
    assert cache.get_many(["x", "y", "z"]) == {"x": 1, "y": 2, "z": 3}

    assert cache.delete_many(["x", "y", "missing"]) == 2
    assert cache.get_many(["x", "y", "z"]) == {"z": 3}


def test_set_many_upserts_existing_keys(db):
    cache.set("p", "old")
    cache.set_many({"p": "new", "q": "fresh"})
    assert cache.get("p") == "new"
    assert cache.get("q") == "fresh"


def test_touch_extends_expiry_without_changing_value(db):
    cache.set("t1", {"big": "x" * 200}, expiration=timedelta(seconds=60))

    assert cache.touch("t1", expiration=timedelta(days=1)) is True
    assert cache.get("t1") == {"big": "x" * 200}  # value untouched


def test_touch_can_clear_expiry(db):
    cache.set("t2", "v", expiration=timedelta(seconds=60))
    assert cache.touch("t2") is True  # expiration=None -> never expires
    assert cache.get("t2") == "v"
    assert CachedItem.query.get(key="t2").expires_at is None  # expiry actually cleared


def test_touch_missing_or_expired_returns_false(db):
    assert cache.touch("does-not-exist") is False

    cache.set("t3", "v", expiration=timedelta(seconds=-1))
    assert cache.touch("t3", expiration=timedelta(days=1)) is False  # already expired


def test_clear_empties_the_cache(db):
    cache.set("c1", 1)
    cache.set("c2", 2)
    assert cache.clear() == 2
    assert cache.get("c1") is None


def test_expiration_rejects_bool_and_date(db):
    with pytest.raises(TypeError):
        cache.set("bad", "v", expiration=True)

    with pytest.raises(TypeError):
        cache.set("bad", "v", expiration=date(2030, 1, 1))  # ty: ignore[invalid-argument-type]


def test_expiration_accepts_aware_datetime(db):
    expires = timezone.now() + timedelta(hours=1)
    cache.set("dt", "v", expiration=expires)
    assert cache.get("dt") == "v"
