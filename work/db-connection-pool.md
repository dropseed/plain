---
labels:
  - plain-models
related:
  - remove-signals
  - models-rename-to-postgres
---

# DB connection pooling

## Problem

Each thread creates and holds its own persistent DB connection. No sharing, no bounds, no health checking beyond `close_if_unusable_or_obsolete`. With `SERVER_THREADS=4` and `SERVER_WORKERS=4`, that's 16 permanent connections — predictable, but not shared or bounded.

## Current behavior

- `get_connection()` lazily creates a `DatabaseConnection` (which holds a psycopg connection) on first access and stores it in a module-level `ContextVar`
- The connection lives on the thread (via ContextVar) until explicitly closed
- `close_old_connections()` runs at request start/finish: checks `CONN_MAX_AGE` (default 600s), closes if stale or broken
- Every request that touches the DB pays a `SELECT 1` health check (via `CONN_HEALTH_CHECKS=True`) on the first cursor access
- No pool, no sharing, no aggregate limit across threads

## What pooling replaces

Pooling subsumes several pieces of existing connection lifecycle machinery:

| Current mechanism                             | What it does                               | Pooling replacement               |
| --------------------------------------------- | ------------------------------------------ | --------------------------------- |
| `CONN_MAX_AGE` (default 600s)                 | Close connections older than N seconds     | Pool `max_lifetime` option        |
| `CONN_HEALTH_CHECKS` + `SELECT 1` per request | Detect broken connections                  | Pool health checks on checkout    |
| `close_old_connections` signal handler        | Run lifecycle checks at request boundaries | Pool manages lifecycle internally |
| `close_if_unusable_or_obsolete()`             | Close stale/broken connections             | Pool handles automatically        |

This is a code simplification win — the pool handles connection lifecycle instead of hand-rolled logic spread across signals, middleware, and wrapper methods.

## Async DB access and SSE/websockets

After the ContextVar migration, async views can access the DB via `loop.run_in_executor()`. Thread pool threads maintain their own persistent connections. This works without pooling — connection count is bounded by `SERVER_THREADS`.

Pooling adds value for SSE/websocket patterns by enabling connections to be shared rather than pinned to threads:

- **Without pooling:** Each of the `SERVER_THREADS` threads holds a persistent connection. SSE polls share the thread pool with regular requests. Works well — connection count stays at `SERVER_THREADS`.
- **With pooling:** Idle threads don't hold connections. Connections are checked out on demand and returned when idle. Useful when `SERVER_THREADS` is increased for I/O-bound workloads but you want fewer DB connections.

For most Plain deployments (few workers, fixed threads), the current per-thread model is adequate. Pooling becomes more valuable at higher thread counts or when external connection limits are tight (managed Postgres services with low connection caps).

### Pooling requires a `db_thread()` helper for async views

Signal/middleware-based return only works for sync views. For async views, `request_finished` fires on a different thread than the one holding the connection (the split pipeline in `BaseHandler`). That thread's ContextVar has its own connection (or none) — it can't return a different thread's connection.

For SSE/websockets, DB calls via `run_in_executor()` check out connections on thread pool threads, but no `request_finished` fires during the stream to return them. Without explicit return, pooling degrades to per-thread persistent connections — defeating the purpose.

The fix is a `db_thread()` helper that returns the connection after each call:

```python
async def db_thread(fn, *args):
    """Run sync DB code in executor, returning connection to pool after."""
    def wrapper():
        try:
            return fn(*args)
        finally:
            conn = _db_conn.get()
            if conn is not None:
                pool.putconn(conn.connection)
                _db_conn.set(None)
    return await asyncio.get_running_loop().run_in_executor(None, wrapper)
```

Usage:

```python
# SSE view
count = await db_thread(User.query.count)  # checkout → query → return

# Transactions: wrap in a single db_thread call
await db_thread(lambda: atomic_update(order_id, status))
```

This helper is **required** for pooling to work correctly with async views — it's not optional.

### Transaction state validation on pool return

Before returning a connection to the pool, validate that no transaction is in progress. If `in_atomic_block` is True or `savepoint_ids` is non-empty, the connection is dirty — it should be rolled back and discarded, not returned to the pool for another request.

## Proposed change

Replace one-connection-per-thread with `psycopg_pool.ConnectionPool`:

```python
from psycopg_pool import ConnectionPool

# One pool per worker process, created at startup
pool = ConnectionPool(
    conninfo=build_conninfo(),
    min_size=4,
    max_size=settings.SERVER_THREADS * 2,
)
```

Connection return at request end replaces `close_old_connections`:

```python
# Signal-based (works today):
def return_connection(**kwargs):
    conn = _db_conn.get()
    if conn is not None:
        pool.putconn(conn.connection)
        _db_conn.set(None)

signals.request_finished.connect(return_connection)

# Or middleware-based (after remove-signals):
def after_response(self, request, response):
    conn = _db_conn.get()
    if conn is not None:
        pool.putconn(conn.connection)
        _db_conn.set(None)
    return response
```

**Benefits:**

- Bounded connection count per worker
- Health checks and stale connection cleanup built into the pool
- Connections shared across threads instead of one-per-thread
- Removes `CONN_MAX_AGE`, `CONN_HEALTH_CHECKS`, and `close_old_connections` complexity

**New dependency:** `psycopg-pool` (pure Python, no platform issues)

## Relationship to pgbouncer

pgbouncer is an external connection pooler between your app and Postgres. In-process pooling and pgbouncer solve overlapping problems:

| Concern                                   | In-process pool                     | pgbouncer                            |
| ----------------------------------------- | ----------------------------------- | ------------------------------------ |
| Connection sharing within a worker        | Yes                                 | No (each app connection is a client) |
| Cross-worker connection limits            | No (each worker has its own pool)   | Yes                                  |
| Health checking                           | Yes (pool tests before handing out) | Yes                                  |
| Extra infrastructure                      | No                                  | Yes (another service to run)         |
| Session-level state (SET, prepared stmts) | Works fine                          | Breaks in transaction pooling mode   |

They can coexist — in-process pool keeps per-worker connections bounded and healthy, pgbouncer keeps aggregate connections across all workers bounded. But for most Plain deployments (few workers, fixed threads), either one alone is sufficient.

## Django's approach (4.2+)

Django 4.2 added native pooling using the same `psycopg_pool.ConnectionPool`:

```python
DATABASES = {
    "default": {
        "OPTIONS": {"pool": True},  # or {"pool": {"min_size": 2, "max_size": 4}}
    }
}
```

This replaced their identical pattern — `threading.local()` holding one connection per thread. It's a sync pool; threads block waiting for a connection if exhausted.

## What gets removed

**From `DatabaseConnection` (wrapper.py):**

- `close_if_unusable_or_obsolete()` — pool handles stale/broken detection
- `close_if_health_check_failed()` — pool health checks on checkout
- `is_usable()` / `SELECT 1` probe — pool handles this internally
- `health_check_done` flag and gating logic in `_cursor()` / `set_autocommit()`
- `close_at` timestamp (set in `connect()`, checked in `close_if_unusable_or_obsolete`)
- `errors_occurred` flag and recovery logic

**From `db.py`:**

- `close_old_connections()` signal handler — replaced by pool return at request end
- `reset_queries()` stays (query log clearing still needed), or moves to middleware

**Settings removed:**

- `POSTGRES_CONN_MAX_AGE` — replaced by pool's `max_lifetime`
- `POSTGRES_CONN_HEALTH_CHECKS` — replaced by pool's built-in health checks

**Settings added:**

- `POSTGRES_POOL` — bool or dict of psycopg_pool options (`min_size`, `max_size`, `max_lifetime`, `timeout`)

## psycopg dependency changes

Currently `psycopg` is not declared as a dependency of plain-models (users install it separately). This proposal also fixes that:

**plain-models dependencies:**

```toml
dependencies = [
    "plain<1.0.0",
    "sqlparse>=0.3.1",
    "psycopg>=3.2.12",
    "psycopg-pool>=3.2",
]
```

- `psycopg` (base) — pure Python, works on all platforms (Alpine, ARM, etc.)
- `psycopg-pool` — pure Python, no platform issues
- `plain start` templates include `psycopg[binary]` in the project's own dependencies for speed

psycopg auto-detects at runtime: prefers `psycopg-c` (compiled from source), falls back to `psycopg-binary` (pre-compiled wheels), falls back to pure Python. So `plain-models` depending on the base package guarantees the driver exists, and users layer on `psycopg[binary]` or `psycopg[c]` in their project for performance. No conflicts — they coexist.

## Implementation details

- Pool uses `configure` callback to run `ensure_timezone` and `ensure_role` on each checkout
- `close()` calls `pool.putconn()` instead of `connection.close()` when pooling
- Connection return at request end: signal handler (today) or middleware `after_response` (after `remove-signals`)

## Managed Postgres services (Neon, Supabase, etc.)

- These services often run their own PgBouncer-style pooler server-side
- Native pooling is complementary — avoids per-request TCP/TLS to the service's pooler endpoint
- Users need guidance on sizing: 8 workers × max_size 4 = 32 connections against a 60-connection limit

## PgBouncer compatibility (separate concern)

- Prepared statements already disabled by default (`prepare_threshold = None`)
- `SET ROLE` via `assume_role` is session-scoped and incompatible with PgBouncer transaction pooling — should document this

## Dependencies

- **ContextVar migration** (done): ContextVar storage is needed so the pool checkout is visible to whichever thread runs the ORM code.
- **`remove-signals`** (optional): Middleware-based lifecycle is cleaner but not required — the pool can also work through signal handlers.
