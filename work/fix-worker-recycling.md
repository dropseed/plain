---
labels:
  - plain.server
---

# Fix: Reintroduce optional worker recycling (Finding 11)

## Status: UNRESOLVED

## Problem

Worker recycling (`max_requests`) was removed. Workers now only restart on crash or timeout. In long-running deployments, workers accumulate memory from fragmentation, C extension leaks, or unbounded caches without any periodic reset.

**Key code locations:**

- `plain/plain/server/arbiter.py` — no recycling logic exists
- `plain/plain/server/connection.py:33` — `conn.req_count` field definition
- `plain/plain/server/http/h1.py:650` — `conn.req_count` incremented after request handling

## Proposed Fix

Add an optional `SERVER_MAX_REQUESTS` setting. When a worker has handled the configured number of requests, it initiates a graceful shutdown (stops accepting, drains in-flight, exits). The arbiter's existing `manage_workers()` will spawn a replacement.

### Changes

**`plain/plain/server/workers/worker.py`**

1. Add a worker-level request counter and max_requests setting:

```python
def __init__(self, ...):
    # ... existing init ...
    from plain.runtime import settings
    self.max_requests = getattr(settings, 'SERVER_MAX_REQUESTS', 0)
    self.max_requests_jitter = getattr(settings, 'SERVER_MAX_REQUESTS_JITTER', 0)
    self.total_requests = 0

    if self.max_requests and self.max_requests_jitter:
        import random
        self.max_requests += random.randint(-self.max_requests_jitter, self.max_requests_jitter)
```

2. Add a `_count_request()` method:

```python
def _count_request(self):
    self.total_requests += 1
    if self.max_requests and self.total_requests >= self.max_requests:
        self.log.info(
            "Worker reached max requests (%d), initiating graceful shutdown",
            self.max_requests,
        )
        self.alive = False
```

Note: `self.total_requests` is only modified from the event loop (single-threaded), so no lock is needed.

**HTTP/1.1 counting:** Call `self._count_request()` after `conn.req_count += 1` in `h1.py`.

**H2 stream counting:** Pass `on_stream_complete=self._count_request` callback to `async_handle_h2_connection`. Store on `H2ConnectionState`. Call in `_async_handle_stream` finally block (which already has the `acquired` flag pattern for budget semaphore release):

```python
async def _async_handle_stream(state, stream):
    budget = state.stream_budget
    acquired = False
    try:
        if budget is not None:
            await budget.acquire()
            acquired = True
        await _async_handle_stream_inner(state, stream)
    finally:
        state.aggregate_body_size -= stream.data_size
        if acquired and budget is not None:
            budget.release()
        if state.on_stream_complete is not None:
            state.on_stream_complete()
```

**Settings (new settings)**

```python
SERVER_MAX_REQUESTS = 0  # 0 = disabled
SERVER_MAX_REQUESTS_JITTER = 0  # random variance, e.g., 50 means +/- 50
```

## Considerations

- Default of 0 (disabled) means no behavior change for existing users.
- H2 streams count individually toward the limit (they exercise the same app code as H1 requests).
- Graceful shutdown via `self.alive = False` stops the accept loop and triggers `_graceful_shutdown()`, which waits for in-flight connections before exiting. The arbiter detects the exit and spawns a replacement.
- Jitter prevents all workers from restarting simultaneously in multi-worker deployments.

### WebSocket considerations

`SERVER_MAX_REQUESTS` counts completed requests toward a recycling limit. WebSocket connections are long-lived — a single WebSocket "request" could last hours. Design the counting so WebSocket upgrades can be excluded later:

- Only count in `_count_request()` which is called from specific sites (H1 request completion, H2 stream completion callback)
- When WebSocket support is added, the WebSocket handler simply doesn't call `_count_request()`, or the callback filters by request type
- The executor health probe is unaffected — WebSockets run on the event loop, not the thread pool
