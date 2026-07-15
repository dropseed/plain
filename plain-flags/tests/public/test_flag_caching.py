"""Contract tests for feature-flag evaluation and per-key caching.

The promise a keyed flag makes: ``get_value()`` runs once per key, the
result is persisted, and later lookups return that stored value. Unkeyed
flags recompute every time. Disabled flags short-circuit.
"""

from __future__ import annotations

import pytest

from plain.flags import Flag
from plain.flags.exceptions import FlagDisabled
from plain.flags.models import Flag as FlagModel
from plain.flags.models import FlagResult


def test_keyed_flag_computes_once_then_caches(db):
    class CountingFlag(Flag):
        calls = 0

        def get_key(self):
            return "user-1"

        def get_value(self):
            CountingFlag.calls += 1
            return "computed"

    assert CountingFlag().value == "computed"
    assert CountingFlag.calls == 1

    # A fresh instance reads the persisted result instead of recomputing.
    assert CountingFlag().value == "computed"
    assert CountingFlag.calls == 1

    # The result was persisted under the key.
    assert FlagResult.query.filter(key="user-1").count() == 1


def test_distinct_keys_cache_independently(db):
    class PerKeyFlag(Flag):
        def __init__(self, key, value):
            self._key = key
            self._value = value

        def get_key(self):
            return self._key

        def get_value(self):
            return self._value

    assert PerKeyFlag("a", "AAA").value == "AAA"
    assert PerKeyFlag("b", "BBB").value == "BBB"

    # Re-evaluating key "a" returns the cached value even though this
    # instance would compute something different — the cache wins.
    assert PerKeyFlag("a", "DIFFERENT").value == "AAA"


def test_unkeyed_flag_recomputes_every_time(db):
    class UnkeyedFlag(Flag):
        calls = 0

        def get_key(self):
            return None

        def get_value(self):
            UnkeyedFlag.calls += 1
            return UnkeyedFlag.calls

    assert UnkeyedFlag().value == 1
    assert UnkeyedFlag().value == 2
    assert UnkeyedFlag.calls == 2

    # Unkeyed flags never persist a result row.
    assert FlagResult.query.count() == 0


def test_disabled_flag_returns_none_when_not_debug(db, settings):
    settings.DEBUG = False

    class MaybeFlag(Flag):
        def get_key(self):
            return "k"

        def get_value(self):
            return "on"

    # First evaluation creates the backing Flag row (enabled by default).
    assert MaybeFlag().value == "on"

    FlagModel.query.filter(name="MaybeFlag").update(enabled=False)

    # Disabled + not DEBUG: degrade gracefully to None rather than crash.
    assert MaybeFlag().value is None


def test_disabled_flag_raises_when_debug(db, settings):
    settings.DEBUG = True

    class StrictFlag(Flag):
        def get_key(self):
            return "k"

        def get_value(self):
            return "on"

    assert StrictFlag().value == "on"
    FlagModel.query.filter(name="StrictFlag").update(enabled=False)

    with pytest.raises(FlagDisabled):
        StrictFlag().value


def test_flag_is_truthy_and_supports_membership(db):
    class ListFlag(Flag):
        def get_key(self):
            return None

        def get_value(self):
            return ["alpha", "beta"]

    flag = ListFlag()
    assert bool(flag) is True
    assert "alpha" in flag
    assert flag == ["alpha", "beta"]

    class OffFlag(Flag):
        def get_key(self):
            return None

        def get_value(self):
            return False

    assert bool(OffFlag()) is False
