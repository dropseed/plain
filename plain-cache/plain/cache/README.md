# plain.cache

**A simple database-backed cache for storing JSON-serializable values with optional expiration.**

- [CLI](#cli)
- [Installation](#installation)

The Plain Cache stores JSON-serializable values in a [`CachedItem`](./models.py#CachedItem) model.
Cached data can be set to expire after a certain amount of time.

Access to the cache is provided through the [`Cached`](./core.py#Cached) class.

```python
from plain.cache import Cached


cached = Cached("my-cache-key")

if cached.exists():
    print("Cache hit and not expired!")
    print(cached.value)
else:
    print("Cache miss!")
    cached.set("a JSON-serializable value", expiration=60)

# Delete the item if you need to
cached.delete()
```

Expired cache items can be cleared by [running chores](/plain/plain/chores/README.md).

## CLI

- `plain cache clear-expired` - Clear all expired cache items
- `plain cache clear-all` - Clear all cache items
- `plain cache stats` - Show cache statistics

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

Run migrations to create the cache tables:

```bash
plain migrate
```
