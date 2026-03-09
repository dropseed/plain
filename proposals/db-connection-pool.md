---
packages:
  - plain-models
depends_on:
  - db-connection-pool-and-contextvars
related:
  - remove-signals
  - models-remove-thread-sharing-validation
---

# DB connection pooling

## Problem

Each thread creates and holds its own persistent DB connection. No sharing, no bounds, no health checking beyond `close_if_unusable_or_obsolete`. With `SERVER_THREADS=4` and `SERVER_WORKERS=4`, that's 16 permanent connections — predictable, but not shared or bounded.

## Current behavior

- `DatabaseConnection.__getattr__` lazily creates a `DatabaseWrapper` (which holds a psycopg connection) on first access
- The connection lives on the thread (via ContextVar) until explicitly closed
- `close_old_connections()` runs at request start/finish: checks `CONN_MAX_AGE` (default 600s), closes if stale or broken
- Every request that touches the DB pays a `SELECT 1` health check (via `CONN_HEALTH_CHECKS=True`) on the first cursor access
- No pool, no sharing, no aggregate limit across threads

## What pooling replaces

Pooling subsumes several pieces of existing connection lifecycle machinery:

| Current mechanism | What it does | Pooling replacement |
|---|---|---|
| `CONN_MAX_AGE` (default 600s) | Close connections older than N seconds | Pool `max_lifetime` option |
| `CONN_HEALTH_CHECKS` + `SELECT 1` per request | Detect broken connections | Pool health checks on checkout |
| `close_old_connections` signal handler | Run lifecycle checks at request boundaries | Pool manages lifecycle internally |
| `close_if_unusable_or_obsolete()` | Close stale/broken connections | Pool handles automatically |

This is a code simplification win — the pool handles connection lifecycle instead of hand-rolled logic spread across signals, middleware, and wrapper methods.

## Async DB access and SSE/websockets

After the ContextVar migration, async views can access the DB via `loop.run_in_executor()`. Thread pool threads maintain their own persistent connections. This works without pooling — connection count is bounded by `SERVER_THREADS`.

Pooling adds value for SSE/websocket patterns by enabling connections to be shared rather than pinned to threads:

- **Without pooling:** Each of the `SERVER_THREADS` threads holds a persistent connection. SSE polls share the thread pool with regular requests. Works well — connection count stays at `SERVER_THREADS`.
- **With pooling:** Idle threads don't hold connections. Connections are checked out on demand and returned when idle. Useful when `SERVER_THREADS` is increased for I/O-bound workloads but you want fewer DB connections.

For most Plain deployments (few workers, fixed threads), the current per-thread model is adequate. Pooling becomes more valuable at higher thread counts or when external connection limits are tight (managed Postgres services with low connection caps).

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

Connection lifecycle for sync views can work through the existing signal handlers or through middleware (if `remove-signals` is done first):

```python
# Signal-based (works today):
def close_old_connections(**kwargs):
    conn = _db_conn.get()
    if conn is not None:
        pool.putconn(unwrap(conn))
        _db_conn.set(None)

# Or middleware-based (after remove-signals):
def before_request(self, request):
    pass  # lazy checkout on first DB access

def after_response(self, request, response):
    conn = _db_conn.get()
    if conn is not None:
        pool.putconn(unwrap(conn))
        _db_conn.set(None)
    return response
```

**Benefits:**

- Bounded connection count per worker
- Health checks and stale connection cleanup built into the pool
- Connections shared across threads instead of one-per-thread
- Removes `CONN_MAX_AGE`, `CONN_HEALTH_CHECKS`, and `close_old_connections` complexity

**New dependency:** `psycopg_pool` (separate install via `pip install psycopg_pool` or `psycopg[pool]`)

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

## Implementation details

- Add `POSTGRES_POOL` setting (bool or dict of psycopg_pool options like `min_size`, `max_size`, `timeout`)
- Incompatible with `POSTGRES_CONN_MAX_AGE != 0` — raise `ImproperlyConfigured`
- Pool uses `configure` callback to run `ensure_timezone` and `ensure_role` on each checkout
- `_close()` calls `putconn()` instead of `connection.close()` when pooling
- Requires `psycopg[pool]` or `psycopg-pool` package

## Managed Postgres services (Neon, Supabase, etc.)

- These services often run their own PgBouncer-style pooler server-side
- Native pooling is complementary — avoids per-request TCP/TLS to the service's pooler endpoint
- Users need guidance on sizing: 8 workers × max_size 4 = 32 connections against a 60-connection limit

## PgBouncer compatibility (separate concern)

- Prepared statements already disabled by default (`prepare_threshold = None`)
- `SET ROLE` via `assume_role` is session-scoped and incompatible with PgBouncer transaction pooling — should document this

## Dependencies

- **`db-connection-pool-and-contextvars`**: ContextVar storage is needed so the pool checkout is visible to whichever thread runs the ORM code.
- **`remove-signals`** (optional): Middleware-based lifecycle is cleaner but not required — the pool can also work through signal handlers.
