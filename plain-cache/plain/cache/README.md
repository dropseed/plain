# plain.cache

**A simple database-backed cache for storing JSON-serializable values with optional expiration.**

- [Overview](#overview)
- [Setting expiration](#setting-expiration)
- [Checking and deleting](#checking-and-deleting)
- [Querying cached items](#querying-cached-items)
- [Automatic cleanup](#automatic-cleanup)
- [CLI commands](#cli-commands)
- [Admin integration](#admin-integration)
- [Settings](#settings)
- [FAQs](#faqs)
- [Installation](#installation)

## Overview

You can store any JSON-serializable value in the cache using the [`Cached`](./core.py#Cached) class. Each cached item is identified by a unique key and can optionally expire after a set amount of time.

```python
from plain.cache import Cached

# Store a value in the cache
cached = Cached("my-cache-key")
cached.set("a JSON-serializable value", expiration=60)  # expires in 60 seconds

# Later, retrieve the value
cached = Cached("my-cache-key")
if cached.exists():
    print(cached.value)  # "a JSON-serializable value"
else:
    print("Cache miss or expired!")
```

Values are stored in a [`CachedItem`](./models.py#CachedItem) database model, so you don't need to set up Redis or any external caching service.

## Setting expiration

You can set expiration in several ways when calling `set()`:

```python
from datetime import datetime, timedelta
from plain.cache import Cached

cached = Cached("my-key")

# Seconds as int or float
cached.set("value", expiration=300)  # 5 minutes

# Timedelta
cached.set("value", expiration=timedelta(hours=1))

# Specific datetime
cached.set("value", expiration=datetime(2025, 12, 31, 23, 59, 59))

# No expiration (cached forever)
cached.set("value")
```

## Checking and deleting

You can check if a cached item exists (and is not expired) using `exists()`:

```python
cached = Cached("my-key")

if cached.exists():
    # Cache hit - value is available
    data = cached.value
else:
    # Cache miss or expired - compute and store the value
    data = expensive_computation()
    cached.set(data, expiration=3600)
```

To delete a cached item:

```python
cached = Cached("my-key")
deleted = cached.delete()  # Returns True if item existed, False otherwise
```

## Querying cached items

The [`CachedItem`](./models.py#CachedItem) model includes a custom queryset with filters for common queries:

```python
from plain.cache.models import CachedItem

# Get all expired items
expired_items = CachedItem.query.expired()

# Get all unexpired items (with an expiration date in the future)
active_items = CachedItem.query.unexpired()

# Get items with no expiration (cached forever)
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

The `exists()` method returns `False` for expired items, and `value` returns `None`. The expired item remains in the database until explicitly cleaned up.

#### Is there any observability built in?

Yes. Cache operations (`exists`, `get`, `set`, `delete`) are instrumented with OpenTelemetry spans, so you can see cache hits and misses in your tracing backend.

#### How big can cached values be?

There's no hard limit. `plain.cache` works well for the typical mix — config, computed flags, tokens, short-lived results, occasional larger payloads. Once values get large enough to TOAST (Postgres' out-of-line storage, kicking in around a few KB), each rewrite produces orphaned TOAST chunks that autovacuum has to reclaim. The defaults in [Settings](#settings) are tuned for this; very high write rates on very large values may need additional tuning. If you're caching megabyte-sized blobs on every request, consider whether that data wants to live somewhere more permanent (a regular table, object storage) with the cache holding a reference instead.

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
from plain.cache import Cached

cached = Cached("test-key")
cached.set({"hello": "world"}, expiration=300)
print(cached.value)  # {'hello': 'world'}
```
