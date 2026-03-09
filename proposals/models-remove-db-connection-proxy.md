---
packages:
  - plain-models
depends_on:
  - db-connection-pool-and-contextvars
---

# Replace `DatabaseConnection` proxy with `get_connection()`

## Problem

`DatabaseConnection` is a stateless proxy class (`__slots__ = ()`, no `__init__`) whose only job is `__getattr__`/`__setattr__` forwarding to a ContextVar-held `DatabaseWrapper`. This made sense when the storage was `threading.local()` hidden inside the object, but after the ContextVar migration the proxy is pure indirection.

Concrete costs:

1. **Type checkers can't see through it.** `db_connection` is typed as `DatabaseConnection`, not `DatabaseWrapper`, so there's no autocomplete or type errors on any attribute access. Three files already work around this with `cast("DatabaseWrapper", db_connection)` (see misc-notes.md).

2. **IDE navigation is broken.** "Find usages" on `DatabaseWrapper.cursor` won't find `db_connection.cursor()` because it goes through `__getattr__`.

3. **Overhead in hot paths.** Every attribute access is 4 hops: `__getattr__` → `_get_or_create_connection` → `_db_conn.get()` → `getattr(conn, attr)`. `transaction.py` does ~25 proxy accesses per `atomic()` enter/exit.

4. **Confusing abstraction.** A class with `__slots__ = ()` and no `__init__` that exists solely for `__getattr__` is unusual. It looks like an object but it's a magic proxy.

## Proposed change

Replace `DatabaseConnection` with module-level functions:

```python
def get_connection() -> DatabaseWrapper:
    """Get or create the database connection for the current context."""
    conn = _db_conn.get()
    if conn is None:
        conn = _create_connection()
        _db_conn.set(conn)
    return conn

def has_connection() -> bool:
    return _db_conn.get() is not None
```

Call sites change from:

```python
from plain.models.db import db_connection

db_connection.cursor()
db_connection.in_atomic_block = True
```

to:

```python
from plain.models.db import get_connection

conn = get_connection()
conn.cursor()
conn.in_atomic_block = True
```

In burst-access code like `transaction.py`, resolve once at the top:

```python
def __enter__(self):
    conn = get_connection()
    conn.needs_rollback = False
    conn.set_autocommit(False)
    conn.in_atomic_block = True
    # ... etc
```

## Migration

- ~120 call sites across 15 files (all internal to plain-models)
- `db_connection` is also used in user code for raw SQL (`db_connection.cursor()`) — the upgrade agent handles the rename
- The three `cast("DatabaseWrapper", ...)` workarounds are deleted
- `configure_settings()` and `create_connection()` become module-level private functions

## Non-goals

- Not changing `DatabaseWrapper` itself — that's a separate concern
- Not changing the ContextVar storage mechanism — that stays as-is
