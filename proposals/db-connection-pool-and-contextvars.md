---
packages:
  - plain-models
related:
  - remove-signals
  - db-connection-pool
---

# DB connections: `threading.local()` → `contextvars.ContextVar`

## Problem

Plain's database layer uses `threading.local()` for per-thread connection storage (`DatabaseConnection._local`). This causes two correctness issues:

1. **Incompatible with async tasks.** Two concurrent async tasks on the same event loop thread share the same `threading.local()` state — same DB connection, same transaction state. If one starts a transaction, the other sees it.

2. **Thread affinity bug.** For async views, `before_request` and `after_response` run in separate `run_in_executor` calls with no guarantee they land on the same thread. With `threading.local()`, `after_response` may check/close a different thread's connection than the one the request actually used. (With ContextVar, both calls see the same connection regardless of thread.)

3. **Manual context propagation.** `loop.run_in_executor()` does NOT propagate `contextvars` (the CPython PR to add this was rejected). `asyncio.to_thread()` does (since Python 3.9). Plain's `BaseHandler._run_in_executor` already does manual OTel context propagation for this reason. With `threading.local()`, there's no context to propagate — each thread just gets whatever state it had from its last request.

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
- Thread affinity — `before_request` and `after_response` see the same ContextVar values regardless of which thread they run on
- `asyncio.to_thread()` automatically propagates context to the worker thread, enabling SSE DB access

**What doesn't change:**

- `DatabaseWrapper` internals stay the same
- `transaction.atomic()` works identically — it reads/writes `db_connection.in_atomic_block` etc., which now resolve through the ContextVar instead of threading.local
- Sync views (99% of usage) see no difference — one task per thread, one ContextVar value per thread

**Gotcha:** Changes to ContextVars inside `to_thread()` do NOT propagate back to the caller. The thread gets a snapshot. This is fine for DB connections — the connection lifecycle is managed by the middleware, not the thread.

**Gotcha:** `loop.run_in_executor()` does NOT copy context. Plain must continue to do manual propagation (as `BaseHandler._run_in_executor` already does for OTel) or switch to `asyncio.to_thread()`.

## SSE / async view DB access

With ContextVar-based connections, SSE views can access the DB via `asyncio.to_thread()`:

```python
class DashboardEventsView(ServerSentEventsView):
    async def stream(self):
        while True:
            count = await asyncio.to_thread(User.query.count)
            yield ServerSentEvent(data=str(count))
            await asyncio.sleep(5)
```

`to_thread()` copies the current context (including the ContextVar holding the DB connection) to the worker thread. The ORM executes synchronously on that thread, using the connection from the context.

The middleware's `after_response` defers cleanup for `AsyncStreamingResponse` (see `remove-signals.md`), so the connection stays alive during streaming.

## Non-goals

- **Async psycopg (`AsyncConnection`)** — not needed for the sync-first architecture. The sync `to_thread()` bridge covers the SSE use case. Free-threaded Python (when psycopg supports it) makes threads genuinely parallel, further reducing the case for async DB drivers.

- **`a`-prefix queryset methods** (`acount()`, `alist()`, etc.) — not needed. Sync methods work via `to_thread()` from async code. Querysets can add `__aiter__` for `async for` iteration without duplicating the API.

## Independence

This change has **no dependencies**. It can ship on its own — the connection lifecycle doesn't change, just the storage mechanism. It's a prerequisite for the optional `db-connection-pool` proposal, but works fine without it.
