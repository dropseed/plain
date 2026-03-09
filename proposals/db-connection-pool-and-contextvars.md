---
packages:
  - plain-models
related:
  - remove-signals
  - db-connection-pool
  - models-remove-db-connection-proxy
  - models-remove-thread-sharing-validation
---

# DB connections: `threading.local()` → `contextvars.ContextVar`

## Problem

Plain's database layer uses `threading.local()` for per-thread connection storage (`DatabaseConnection._local`). This causes two correctness issues:

1. **Incompatible with async tasks.** Two concurrent async tasks on the same event loop thread share the same `threading.local()` state — same DB connection, same transaction state. If one starts a transaction, the other sees it.

2. **Blocks async DB access.** With `threading.local()`, there's no mechanism for async views to access the DB. ContextVars enable `loop.run_in_executor()` to run ORM code on thread pool threads, where each thread maintains its own persistent connection via its native ContextVar context.

## Proposed change

Replace the thread-local connection storage with a `ContextVar`:

```python
import contextvars

_db_conn: contextvars.ContextVar[DatabaseWrapper | None] = contextvars.ContextVar(
    '_db_conn', default=None
)

class DatabaseConnection:
    def has_connection(self) -> bool:
        return _db_conn.get() is not None

    def __getattr__(self, attr: str) -> Any:
        conn = _db_conn.get()
        if conn is None:
            conn = self.create_connection()
            _db_conn.set(conn)
        return getattr(conn, attr)
```

**What this fixes:**

- Async task isolation — each `asyncio.Task` gets its own context copy (since Python 3.7.1)
- Enables async DB access — async views can call `loop.run_in_executor(None, User.query.count)` to run ORM code on thread pool threads that maintain their own persistent connections

**What doesn't change:**

- `DatabaseWrapper` internals stay the same
- `transaction.atomic()` works identically — it reads/writes `db_connection.in_atomic_block` etc., which now resolve through the ContextVar instead of threading.local
- Sync views (99% of usage) see no difference — one task per thread, one ContextVar value per thread

**Key behavior:** `loop.run_in_executor()` does NOT copy the calling context to the worker thread (the CPython PR to add this was rejected in favor of `asyncio.to_thread()`). Each `ThreadPoolExecutor` worker thread maintains its own native ContextVar context that persists across work items. This means ContextVar values set during one request persist for the next request on the same thread — matching the old `threading.local()` behavior and preserving CONN_MAX_AGE connection reuse. `_run_in_executor` propagates only OTel context explicitly — DB connections are intentionally left on the thread's native context.

## SSE / async view DB access

With ContextVar-based connections, SSE views can access the DB via `loop.run_in_executor()`:

```python
class DashboardEventsView(ServerSentEventsView):
    async def stream(self):
        loop = asyncio.get_running_loop()
        while True:
            count = await loop.run_in_executor(None, User.query.count)
            yield ServerSentEvent(data=str(count))
            await asyncio.sleep(5)
```

`run_in_executor()` dispatches the ORM call to a thread pool thread. That thread has its own native ContextVar context with a persistent DB connection (created on first access, reused across calls via CONN_MAX_AGE). No context copying, no connection lifecycle issues.

**Why `run_in_executor()` and not `asyncio.to_thread()`:** `to_thread()` copies the calling context to the worker thread via `copy_context().run()`. The async task's context has `_db_conn=None`, so each `to_thread()` call would create a new connection that's orphaned when the copied context is discarded. `run_in_executor()` avoids this by letting each thread maintain its own persistent connection.

**Note:** With this pattern, SSE polls share the existing `SERVER_THREADS` thread pool with regular requests. Connection count stays bounded at `SERVER_WORKERS × SERVER_THREADS`. The thread pool is the concurrency limit, not the connection count.

## Non-goals

- **Async psycopg (`AsyncConnection`)** — not needed for the sync-first architecture. The sync `run_in_executor()` bridge covers the SSE use case. Free-threaded Python (when psycopg supports it) makes threads genuinely parallel, further reducing the case for async DB drivers.

- **`a`-prefix queryset methods** (`acount()`, `alist()`, etc.) — not needed. Sync methods work via `run_in_executor()` from async code. A `db_thread()` helper or queryset `__aiter__` could provide ergonomic wrappers without duplicating the API.

## Independence

This change has **no dependencies**. It can ship on its own — the connection lifecycle doesn't change, just the storage mechanism. It's a prerequisite for the optional `db-connection-pool` proposal, but works fine without it.
