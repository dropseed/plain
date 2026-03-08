---
packages:
  - plain-models
depends_on:
  - remove-signals
  - db-connection-pool-and-contextvars
---

# DB connection pooling

## Problem

Each thread creates and holds its own persistent DB connection. No sharing, no bounds, no health checking beyond `close_if_unusable_or_obsolete`. With `SERVER_THREADS=4` and `SERVER_WORKERS=4`, that's 16 permanent connections — predictable, but not shared or bounded.

## Current behavior

- `DatabaseConnection.__getattr__` lazily creates a `DatabaseWrapper` (which holds a psycopg connection) on first access
- The connection lives on the thread (via `threading.local()`, or after the contextvars proposal, via `ContextVar`) until explicitly closed
- `close_old_connections()` runs at request start/finish: checks `CONN_MAX_AGE` (default 600s), closes if stale or broken
- No pool, no sharing, no aggregate limit across threads

## Is this even needed?

With Plain's fixed thread count, the current model is reasonable:

- Total connections = `SERVER_WORKERS` x `SERVER_THREADS` (predictable, small)
- pgbouncer in front handles connection limits when scaling to many workers/pods, with no code changes

What the current model lacks:

- **No connection sharing** — if a thread is rendering a template, its connection sits idle
- **No aggregate limit** — 8 workers x 8 threads = 64 connections (Postgres default max is 100)
- **No health checking between requests** — stale connections detected only at request boundaries

pgbouncer solves all of these externally. In-process pooling (Django-style) solves sharing and health checks but not cross-worker limits.

## Proposed change (if pursued)

Replace one-connection-per-thread with `psycopg_pool.ConnectionPool`:

```python
from psycopg_pool import ConnectionPool

# One pool per worker process, created at startup
pool = ConnectionPool(
    conninfo=build_conninfo(),
    min_size=4,
    max_size=settings.SERVER_THREADS * 2,
)

# In DatabaseConnectionMiddleware:
def before_request(self, request):
    conn = pool.getconn()
    _db_conn.set(wrap_connection(conn))
    return None

def after_response(self, request, response):
    conn = _db_conn.get()
    if conn is not None:
        pool.putconn(unwrap_connection(conn))
        _db_conn.set(None)
    return response
```

**Benefits:**

- Bounded connection count per worker
- Health checks and stale connection cleanup built into the pool
- Connections shared across threads instead of one-per-thread
- `CONN_MAX_AGE` logic moves to pool configuration

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
- Pool uses `configure` callback to run `_configure_timezone` and `_configure_role` on each checkout
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

- **`remove-signals`**: Middleware-based lifecycle is needed so `before_request` / `after_response` can check out and return connections.
- **`db-connection-pool-and-contextvars`**: ContextVar storage is needed so the checked-out connection is visible regardless of which thread runs the middleware. Without it, returning a connection in `after_response` on a different thread than `before_request` would return the wrong connection.
