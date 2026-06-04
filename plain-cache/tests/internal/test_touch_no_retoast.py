"""touch() must not re-TOAST the value -- the whole point of the method.

Pins the storage-level behavior: updating only expires_at/updated_at reuses the
existing TOAST pointer, so a large value is not re-written. Re-set()ing the same
value *does* re-TOAST, which is exactly the cost touch() avoids.
"""

from __future__ import annotations

import base64
import os
from datetime import timedelta

from plain.cache import cache
from plain.postgres import get_connection


def _toast_bytes() -> int:
    with get_connection().cursor() as cur:
        cur.execute(
            "SELECT pg_relation_size(reltoastrelid) FROM pg_class "
            "WHERE relname = 'plaincache_cacheditem'"
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


def test_touch_writes_no_new_toast_chunks(db):
    # High-entropy ~2.7 MB value so TOAST compression can't mask the effect.
    big = {"blob": base64.b64encode(os.urandom(2_000_000)).decode()}

    cache.set("toast_probe", big, expiration=timedelta(days=30))
    after_set = _toast_bytes()

    cache.touch("toast_probe", expiration=timedelta(days=60))
    after_touch = _toast_bytes()

    cache.set("toast_probe", big, expiration=timedelta(days=90))
    after_reset = _toast_bytes()

    # touch() added no TOAST bytes; re-set()ing the same value did.
    assert after_touch == after_set
    assert after_reset > after_set
