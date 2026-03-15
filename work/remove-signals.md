---
labels:
- plain.signals
- plain-models
- plain-jobs
related:
- response-defer
- db-connection-pool
---

# Remove signals from Plain

## Problem

The signals system (`request_started`, `request_finished`) causes problems:

1. **Threading fragility** — The handler must ensure signals fire on the correct thread because `DatabaseConnection` uses `threading.local()`. This constraint leaked into the async view design (two executor calls just to keep signals on the right thread).

2. **Implicit coupling** — `plain-models` silently hooks into the request lifecycle at import time via `signals.request_started.connect(...)`. The handler has no idea what's listening or what those listeners need.

3. **Overkill** — The `Signal` class has weak references, sender filtering, dispatch UIDs, `send_robust()`, thread-safe locking. All of it serves two function calls in one package (`plain-models`).

## Current usage

The **entire** signals system is just `request_started` and `request_finished`. No other signal types exist.

### Senders (2 places)

- `plain/internal/handlers/base.py` — sends both on request start/finish
- `plain-jobs/workers.py` — sends both around job execution

### Receivers (2 functions, both in `plain-models`)

- `reset_queries()` on `request_started` — clears debug query log
- `close_old_connections()` on `request_started` and `request_finished` — closes stale/broken DB connections

## Decision

### HTTP: DatabaseConnectionMiddleware

Replace signals with a `DatabaseConnectionMiddleware` that users add to `settings.MIDDLEWARE`, just like `SessionMiddleware`:

```python
class DatabaseConnectionMiddleware(HttpMiddleware):
    def before_request(self, request):
        if db_connection.has_connection():
            db_connection.queries_log.clear()
            db_connection.close_if_unusable_or_obsolete()
        return None

    def after_response(self, request, response):
        if db_connection.has_connection():
            db_connection.close_if_unusable_or_obsolete()
        return response
```

The `/plain-install` skill adds it to `MIDDLEWARE` when installing `plain-models`. Users can see it, reorder it, understand it. No magic registration.

### Jobs: direct calls

`plain-jobs` already hard-depends on `plain-models` (jobs are stored in the DB). Replace the `request_started.send()` / `request_finished.send()` calls in `process_job()` with direct calls to `reset_queries()` and `close_old_connections()`.

### Delete plain.signals

Remove the module entirely. No deprecation period — the upgrade agent can handle any third-party code that was using it (unlikely, since only `plain-models` used it).

## Streaming response lifecycle

Moving to middleware opens up something signals couldn't do: `after_response` can inspect the response object and adapt its behavior for streaming.

Today, `request_finished` (and therefore `close_old_connections`) fires in `_finish_pipeline` before the response body is transmitted. For regular responses this is fine. For `AsyncStreamingResponse` (SSE), it means DB connections are cleaned up before `stream()` even starts iterating — so any DB access inside `stream()` would need its own connection management.

As middleware, `DatabaseConnectionMiddleware.after_response` can detect streaming responses and defer cleanup:

```python
class DatabaseConnectionMiddleware(HttpMiddleware):
    def before_request(self, request):
        if db_connection.has_connection():
            db_connection.queries_log.clear()
            db_connection.close_if_unusable_or_obsolete()
        return None

    def after_response(self, request, response):
        if isinstance(response, AsyncStreamingResponse):
            # Defer cleanup to response.close() so the DB connection
            # stays alive during streaming. The stream() coroutine can
            # use sync_to_async() to access the DB on a thread that
            # shares this connection.
            response._resource_closers.append(
                lambda: db_connection.close_if_unusable_or_obsolete()
            )
        else:
            if db_connection.has_connection():
                db_connection.close_if_unusable_or_obsolete()
        return response
```

This doesn't fully solve DB access in SSE views — `stream()` runs on the event loop where there's no thread-local DB connection. A `sync_to_async` bridge is still needed to run queries on a thread pool thread. But deferred cleanup ensures the connection isn't prematurely closed while streaming is in progress.

Once signals are gone, the two-executor-call split for async views simplifies. Middleware `before_request` and `after_response` both run in the executor, but no longer need to guarantee the same thread for signal handler thread-local state. The thread-affinity question is already resolved — with ContextVar storage (done), `after_response` sees the same connection regardless of which thread it runs on.

## Implementation

1. Add `DatabaseConnectionMiddleware` to `plain-models`
2. Update `/plain-install` skill to add it to `MIDDLEWARE`
3. Replace signal sends in `plain-jobs/workers.py` with direct function calls
4. Remove signal connects from `plain-models` package config
5. Remove `request_started` / `request_finished` sends from `BaseHandler`
6. Delete `plain/signals.py` and `plain.signals` module
7. Remove test fixtures that disconnect/reconnect signal handlers
