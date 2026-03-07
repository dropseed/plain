---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- fix-blocking-async-views
- remove-signals
---

# Fix: Async view lifecycle thread affinity (Finding 8)

## Status: UNRESOLVED

## Problem

For async views, `BaseHandler.handle()` makes two separate `run_in_executor` calls:

1. **First call** (line 167-168): `_run_sync_pipeline` runs `request_started` signal, before-middleware, and URL resolution
2. **Second call** (line 180-186): `_finish_pipeline` runs after-middleware and `request_finished` signal

Between these, the async view coroutine runs on the event loop (line 175).

`ThreadPoolExecutor` provides no guarantee that both calls land on the same thread. The docstring at line 242 says "request_finished is sent here (on the same thread as request_started)" -- this is true for sync views but **false for async views**.

**Key code location:** `plain/plain/internal/handlers/base.py:136-192`

## Impact

- `close_old_connections` (connected to both `request_started` and `request_finished` at `plain-models/plain/models/db.py:43-44`) uses thread-local database connections. If `request_finished` fires on a different thread than `request_started`, it may close a connection belonging to another request, or fail to close the one from the original thread.
- Any user signal handler that stores thread-local state in `request_started` and reads it in `request_finished` will see stale or missing data.
- OTel context is propagated via `_run_in_executor`'s wrapper (line 116-134), so tracing is not affected. This is specifically a thread-local storage issue.

## Proposed Fix

Pin both executor calls to the same thread for a given request. Two approaches:

### Option A: Use a single-thread executor per request (simple)

```python
async def handle(self, request, executor):
    # ... span setup ...

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as req_executor:
        result = await self._run_in_executor(req_executor, self._run_sync_pipeline, request)

        if isinstance(result, _AsyncViewPending):
            try:
                response = await result.coroutine
                self._check_response(response, result.view_class)
            except Exception as exc:
                response = response_for_exception(request, exc)

            response = await self._run_in_executor(
                req_executor, self._finish_pipeline, request, response, result.ran_before
            )
        else:
            response = result
```

**Trade-off:** Creates a throwaway executor per async view request. This is cheap (Python thread pools are lazy -- the thread is only created on first submit and reused for the second), but adds some overhead vs the shared pool.

### Option B: Submit both as a single executor call (preferred)

Restructure so async views still use a single executor call. Move the coroutine awaiting into the sync pipeline via `asyncio.run_coroutine_threadsafe`:

This is more complex and would require the thread to block while the event loop runs the coroutine. Not recommended due to deadlock risk with bridge connections.

### Option C: Update the docstring and accept the trade-off

The `close_old_connections` handler is idempotent -- it checks `has_connection()` on the current thread and closes if stale. If it runs on a different thread, it simply operates on that thread's connection (or no-ops if there isn't one). The practical risk is low because:

1. Thread-local DB connections are per-thread, so `close_old_connections` on Thread B won't affect Thread A's connection
2. The "missed cleanup" on the original thread will be caught by the next `request_started` on that thread

This is the lowest-effort option but should be documented clearly.

## Recommendation

Option A is the cleanest fix with minimal risk. The overhead of a single-thread executor is negligible compared to actual request processing time. Update the docstring at line 242-247 to accurately describe the behavior for both sync and async views.
