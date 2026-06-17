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


def test_increment_starts_at_delta_on_a_missing_key(db):
    assert cache.increment("counter") == 1  # default delta
    assert cache.increment("counter") == 2  # accumulates
    assert cache.increment("counter", 5) == 7
    assert cache.get("counter") == 7


def test_decrement_subtracts(db):
    cache.increment("d", 10)
    assert cache.decrement("d", 3) == 7
    assert cache.decrement("d") == 6  # default delta
    assert cache.get("d") == 6


def test_increment_sets_expiry_only_on_a_fresh_window(db):
    cache.increment("win", expiration=timedelta(hours=1))
    deadline = CachedItem.query.get(key="win").expires_at
    assert deadline is not None

    # A live increment ignores `expiration` and keeps the original deadline.
    cache.increment("win", expiration=timedelta(days=99))
    assert CachedItem.query.get(key="win").expires_at == deadline
    assert cache.get("win") == 2


def test_increment_resets_an_expired_window(db):
    cache.increment("rl", expiration=timedelta(hours=1))
    cache.increment("rl")
    assert cache.get("rl") == 2

    # Force the window into the past: it now reads as absent.
    CachedItem.query.filter(key="rl").update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert cache.get("rl") is None

    # The next increment restarts the count and takes a fresh deadline rather
    # than resuming the stale total on a lapsed window.
    assert cache.increment("rl", expiration=timedelta(hours=1)) == 1
    new_deadline = CachedItem.query.get(key="rl").expires_at
    assert new_deadline is not None
    assert new_deadline > timezone.now()


def test_increment_treats_a_none_value_as_zero(db):
    # None is a legitimately stored value (a "hit"), but it isn't a number --
    # incrementing it starts a counter from delta rather than erroring.
    cache.set("n", None)
    assert cache.increment("n", 5) == 5
    assert cache.get("n") == 5


def test_increment_on_a_non_number_raises(db):
    import psycopg

    cache.set("text", "not a number")
    with pytest.raises(psycopg.DataError):
        cache.increment("text")


def test_increment_rejects_a_numeric_looking_string(db):
    # A JSON string is not a JSON number, even when it looks like one --
    # increment() must raise, not silently coerce "5" into the number 6.
    import psycopg

    cache.set("s", "5")
    with pytest.raises(psycopg.DataError):
        cache.increment("s")


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
