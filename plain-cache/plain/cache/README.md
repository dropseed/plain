# plain.cache

**A simple database-backed cache for storing JSON-serializable values with optional expiration.**

- [Overview](#overview)
- [Setting expiration](#setting-expiration)
- [Get-or-set](#get-or-set)
- [Batch operations](#batch-operations)
- [Refreshing expiration](#refreshing-expiration)
- [Checking and deleting](#checking-and-deleting)
- [Querying cached items](#querying-cached-items)
- [Automatic cleanup](#automatic-cleanup)
- [CLI commands](#cli-commands)
- [Admin integration](#admin-integration)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

Import the [`cache`](./core.py#Cache) and store any JSON-serializable value under a key. Each entry can optionally expire after a set amount of time.

```python
from plain.cache import cache

# Store a value (expires in 60 seconds)
cache.set("my-cache-key", "a JSON-serializable value", expiration=60)

# Later, read it back (returns None on a miss or if expired)
value = cache.get("my-cache-key")
```

`cache` is a stateless module-level store, so there's nothing to instantiate — just import it and call. Values live in a [`CachedItem`](./models.py#CachedItem) database model, so you don't need to set up Redis or any external caching service.

Reads are **expiry-aware**: an entry past its `expires_at` reads as absent (`get()` returns the default, `exists()` returns `False`). Expired rows are deleted out of band — see [Automatic cleanup](#automatic-cleanup).

## Setting expiration

`set()` accepts expiration as seconds, a `timedelta`, or an absolute `datetime`. Omitting it stores the value with no expiration.

```python
from datetime import datetime, timedelta
from plain.cache import cache

# Seconds as int or float
cache.set("k", "value", expiration=300)  # 5 minutes

# Timedelta
cache.set("k", "value", expiration=timedelta(hours=1))

# Specific datetime
cache.set("k", "value", expiration=datetime(2025, 12, 31, 23, 59, 59))

# No expiration (cached forever)
cache.set("k", "value")
```

`set()` always rewrites the whole entry, including its expiry. To change only the expiry without rewriting the value, use [`touch()`](#refreshing-expiration).

## Get-or-set

`get_or_set()` returns the cached value, or computes it, stores it, and returns it on a miss. `default` can be a value or a zero-arg callable (the callable runs only on a miss):

```python
from datetime import timedelta
from plain.cache import cache

data = cache.get_or_set(
    "report:42",
    lambda: build_expensive_report(42),
    expiration=timedelta(hours=1),
)
```

A stored `None` counts as a hit, so caching a computed `None` won't recompute it every time.

## Batch operations

Read or write many keys at once. `get_many()` is a single query and returns only the live entries:

```python
from plain.cache import cache

cache.set_many({"a": 1, "b": 2, "c": 3}, expiration=timedelta(minutes=5))

cache.get_many(["a", "b", "missing"])  # {"a": 1, "b": 2}

cache.delete_many(["a", "b"])  # returns the number deleted
```

## Refreshing expiration

To extend or change a live entry's expiration _without_ rewriting its value, use `touch()`:

```python
from datetime import timedelta
from plain.cache import cache

touched = cache.touch("my-key", expiration=timedelta(days=30))  # True if live, else False
```

`set()` always rewrites `value`, so refreshing a large entry's TTL re-TOASTs the whole blob. `touch()` writes only `expires_at` (and `updated_at`) — a heap-only write that reuses the existing TOAST pointer — so a multi-megabyte value isn't re-written. For refresh-heavy caches of large values (e.g. a conditional-request response cache with a sliding TTL), this avoids the dominant write cost.

`touch()` returns `False` for a missing or already-expired key (it won't resurrect an expired entry). Passing `expiration=None` clears the expiry so the entry never expires.

## Checking and deleting

```python
from plain.cache import cache

# Check for a live entry without fetching the value
if cache.exists("my-key"):
    ...

# Delete a single key (True if it existed)
cache.delete("my-key")

# Delete everything
cache.clear()  # returns the number of rows deleted
```

## Querying cached items

The [`CachedItem`](./models.py#CachedItem) model includes a custom queryset with filters for common queries:

```python
from plain.cache.models import CachedItem

# Live entries (never-expiring or not-yet-expired) -- what reads use
live_items = CachedItem.query.live()

# Expired items (past their expiration)
expired_items = CachedItem.query.expired()

# Unexpired items with a *future* expiration date (excludes forever items)
unexpired_items = CachedItem.query.unexpired()

# Items with no expiration (cached forever)
forever_items = CachedItem.query.forever()
```

## Automatic cleanup

Expired cache items are not automatically deleted from the database. You can clean them up in two ways:

1. **Using chores**: If you have [plain.chores](/plain/plain/chores/README.md) set up, the `ClearExpired` chore will automatically delete expired items when chores run.

2. **Using the CLI**: Run `plain cache clear-expired` manually or in a scheduled task.

## CLI commands

The `plain cache` command group provides utilities for managing cached items:

- `plain cache stats` - Show cache statistics (total, expired, unexpired, forever counts)
- `plain cache clear-expired` - Delete all expired cache items
- `plain cache clear-all` - Delete all cache items (prompts for confirmation)

## Admin integration

If you have [plain.admin](/plain-admin/plain/admin/README.md) installed, `plain.cache` automatically registers an admin viewset. You can browse cached items, see their keys, values, and expiration dates in the admin interface under the "Cache" section.

## Settings

| Setting                               | Default |
| ------------------------------------- | ------- |
| `CACHE_AUTOVACUUM_SCALE_FACTOR`       | `0.1`   |
| `CACHE_TOAST_AUTOVACUUM_SCALE_FACTOR` | `0.05`  |

The cache table is a high-churn workload — every `set()` rewrites a row, and large values get TOASTed (Postgres' out-of-line storage), where each rewrite leaves orphaned chunks. Postgres' default autovacuum scale factor (`0.2`) waits until 20% of tuples are dead, which is too lax here. Plain ships tighter defaults so autovacuum keeps the heap and TOAST tables healthy without manual intervention.

These are applied as per-table storage parameters on `plaincache_cacheditem` by `plain postgres sync`. Override via `app/settings.py` or `PLAIN_CACHE_*` env vars. See [`default_settings.py`](./default_settings.py) for context.

## FAQs

#### What types of values can I cache?

Any JSON-serializable value: strings, numbers, booleans, lists, dicts, and None. Complex objects need to be serialized before caching.

#### What happens when I access an expired item?

`get()` returns the default (`None` unless you pass one) and `exists()` returns `False` — an expired entry reads as absent. The row remains in the database until cleaned up (see [Automatic cleanup](#automatic-cleanup)).

#### How big can cached values be?

There's no hard limit. `plain.cache` works well for the typical mix — config, computed flags, tokens, short-lived results, occasional larger payloads. Once values get large enough to TOAST (Postgres' out-of-line storage, kicking in around a few KB), each rewrite produces orphaned TOAST chunks that autovacuum has to reclaim. The defaults in [Settings](#settings) are tuned for this; very high write rates on very large values may need additional tuning. If you're caching megabyte-sized blobs on every request, consider whether that data wants to live somewhere more permanent (a regular table, object storage) with the cache holding a reference instead — and use [`touch()`](#refreshing-expiration) to slide their TTLs instead of re-`set()`ing them.

## Installation

Install the `plain.cache` package from [PyPI](https://pypi.org/project/plain.cache/):

```bash
uv add plain.cache
```

Add `plain.cache` to your `INSTALLED_PACKAGES`:

```python
# app/settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.cache",
]
```

Sync the database to create the cache tables:

```bash
plain postgres sync
```

Try it out:

```python
from plain.cache import cache

cache.set("test-key", {"hello": "world"}, expiration=300)
print(cache.get("test-key"))  # {'hello': 'world'}
```
