from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from plain.utils import timezone

if TYPE_CHECKING:
    from .models import CachedItem

# An expiration argument: seconds (int/float), a timedelta, an absolute
# datetime, or None for "never expires".
Expiration = datetime | timedelta | int | float | None


def _coerce_expiration(expiration: Expiration, *, now: datetime) -> datetime | None:
    """Resolve an `expiration` argument to a timezone-aware `datetime`, or `None`
    for "never expires". Relative expirations are measured from `now`, which the
    caller passes in so a single write derives its expiry and row timestamps from
    one instant.

    Accepts seconds (`int`/`float`), a `timedelta`, or an absolute `datetime`.
    Unsupported types are rejected loudly rather than silently treated as "no
    expiry" -- in particular a `bool` (which is an `int` subclass) and a bare
    `date` (which is not a `datetime`) are common mistakes.
    """
    if expiration is None:
        return None

    if isinstance(expiration, bool):
        raise TypeError(
            "expiration must be seconds, a timedelta, or a datetime -- not a bool"
        )

    if isinstance(expiration, int | float):
        expires_at = now + timedelta(seconds=expiration)
    elif isinstance(expiration, timedelta):
        expires_at = now + expiration
    elif isinstance(expiration, datetime):
        expires_at = expiration
    else:
        raise TypeError(
            "expiration must be seconds, a timedelta, or a datetime -- got "
            f"{type(expiration).__name__}"
        )

    if not timezone.is_aware(expires_at):
        expires_at = timezone.make_aware(expires_at)
    return expires_at


class Cache:
    """A key/value cache backed by the `CachedItem` Postgres model.

    Reads are expiry-aware: an entry past its `expires_at` reads as absent (the
    `clear_expired` chore / `plain cache clear-expired` deletes it out of band).
    Stateless -- nothing is held between calls, so every read reflects the
    current row. Stored values must be JSON-serializable.

    Use the module-level `cache` singleton: `from plain.cache import cache`.
    """

    @property
    def _model(self) -> type[CachedItem]:
        # Imported lazily so `from plain.cache import cache` works at import time,
        # before the packages registry is ready.
        from .models import CachedItem

        return CachedItem

    # Reading -----------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for `key`, or `default` if it's absent or expired."""
        item = self._model.query.live().filter(key=key).first()
        return item.value if item is not None else default

    def get_many(self, keys: Iterable[str]) -> dict[str, Any]:
        """Return a `{key: value}` dict of the live entries among `keys`.

        Missing/expired keys are omitted. One query regardless of how many keys.
        """
        items = self._model.query.live().filter(key__in=list(keys))
        return {item.key: item.value for item in items}

    # Writing -----------------------------------------------------------------

    def set(self, key: str, value: Any, *, expiration: Expiration = None) -> None:
        """Store `value` under `key`. `expiration=None` (the default) never expires.

        Always rewrites the whole entry, including its expiry -- to change only
        the expiry of a large value without rewriting it, use `touch()`.
        """
        # A single-key upsert -- same one-statement INSERT ... ON CONFLICT path
        # as set_many(), so set/set_many share one write mechanism.
        self.set_many({key: value}, expiration=expiration)

    def set_many(
        self, mapping: Mapping[str, Any], *, expiration: Expiration = None
    ) -> None:
        """Store every `{key: value}` in `mapping` with a shared expiration."""
        if not mapping:
            return

        # bulk_create fires pre_save, so updated_at's update_now stamps a fresh
        # now() at write time on its own. created_at (no update_now) would
        # otherwise fall to its DB default, evaluated a hair later -- leaving a
        # brand-new row with updated_at < created_at. Stamp created_at from an
        # up-front `now` so created_at <= updated_at; it's omitted from
        # update_fields, so it's preserved on conflict.
        now = timezone.now()
        expires_at = _coerce_expiration(expiration, now=now)
        items = [
            self._model(key=key, value=value, expires_at=expires_at, created_at=now)
            for key, value in mapping.items()
        ]
        self._model.query.bulk_create(
            items,
            update_conflicts=True,
            update_fields=["value", "expires_at", "updated_at"],
            unique_fields=["key"],
        )

    def get_or_set(
        self,
        key: str,
        default: Callable[[], Any] | Any,
        *,
        expiration: Expiration = None,
    ) -> Any:
        """Return the value for `key`, computing and storing it on a miss.

        `default` may be a value or a zero-arg callable; the callable is only
        invoked on a miss (so a callable can't be cached *as* the value). A
        stored `None` counts as a hit (it won't recompute).
        """
        item = self._model.query.live().filter(key=key).first()
        if item is not None:
            return item.value

        value = default() if callable(default) else default
        self.set(key, value, expiration=expiration)
        return value

    def touch(self, key: str, *, expiration: Expiration = None) -> bool:
        """Change a live entry's expiration *without* rewriting its value.

        `set()` always rewrites `value`, so refreshing a large entry's TTL
        re-TOASTs the whole blob. `touch()` writes only `expires_at` and
        `updated_at` -- a heap-only write that reuses the existing TOAST pointer,
        so a multi-megabyte value isn't re-written. Ideal for a sliding-TTL cache
        of large values.

        `expiration=None` clears the expiry (never expires). Returns `True` if a
        live entry was updated, `False` if `key` is absent or already expired.
        """
        # QuerySet.update() issues a direct SQL UPDATE and does NOT fire pre_save,
        # so updated_at's update_now won't bump on its own -- stamp it by hand.
        # (set_many() relies on pre_save instead, since bulk_create does fire it.)
        now = timezone.now()
        updated = (
            self._model.query.live()
            .filter(key=key)
            .update(expires_at=_coerce_expiration(expiration, now=now), updated_at=now)
        )
        return updated > 0

    # Deleting ----------------------------------------------------------------

    def delete(self, key: str) -> bool:
        """Delete `key`. Returns `True` if it existed, `False` otherwise."""
        return self._model.query.filter(key=key).delete() > 0

    def delete_many(self, keys: Iterable[str]) -> int:
        """Delete every key in `keys`. Returns the number of rows deleted."""
        return self._model.query.filter(key__in=list(keys)).delete()

    def clear(self) -> int:
        """Delete every entry in the cache. Returns the number of rows deleted."""
        return self._model.query.all().delete()


cache = Cache()
