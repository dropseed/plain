---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- fix-worker-timeout
---

# Fix: Reintroduce optional worker recycling (Finding 11)

## Status: UNRESOLVED

## Problem

Worker recycling (`max_requests`) was removed. Workers now only restart on crash or timeout. In long-running deployments, workers accumulate memory from fragmentation, C extension leaks, or unbounded caches without any periodic reset.

**Key code locations:**

- `plain/plain/server/arbiter.py` - no recycling logic exists
- `plain/plain/server/workers/thread.py` - `conn.req_count` is tracked (line 205, 501) but never checked against a limit

## Proposed Fix

Add an optional `SERVER_MAX_REQUESTS` setting. When a worker has handled the configured number of requests, it initiates a graceful shutdown (stops accepting, drains in-flight, exits). The arbiter's existing `manage_workers()` will spawn a replacement.

### Changes

**`plain/plain/server/workers/thread.py`**

1. Add a worker-level request counter and max_requests setting:

```python
def __init__(self, ...):
    # ... existing init ...
    from plain.runtime import settings
    self.max_requests = getattr(settings, 'SERVER_MAX_REQUESTS', 0)
    self.total_requests = 0
```

2. After each request completes in `_handle_connection`, increment and check:

```python
# After _dispatch returns (around line 503-504):
conn.req_count += 1
self.total_requests += 1

if self.max_requests and self.total_requests >= self.max_requests:
    self.log.info(
        "Worker reached max requests (%d), initiating graceful shutdown",
        self.max_requests,
    )
    self.alive = False
```

Note: `self.total_requests` is only modified from the event loop (single-threaded), so no lock is needed.

**Settings (new setting)**

Add `SERVER_MAX_REQUESTS` with default `0` (disabled). Optionally add jitter to prevent thundering herd when all workers hit the limit simultaneously:

```python
SERVER_MAX_REQUESTS = 0  # 0 = disabled
SERVER_MAX_REQUESTS_JITTER = 0  # random variance, e.g., 50 means +/- 50
```

With jitter, the effective limit per worker would be `max_requests + random.randint(-jitter, jitter)`.

## Considerations

- Default of 0 (disabled) means no behavior change for existing users.
- The counter tracks connections with at least one completed request, not individual HTTP/2 streams. For H2, each stream dispatched through `_async_handle_stream` could also increment a counter, but connection-level counting is simpler and sufficient for the memory-leak use case.
- Graceful shutdown via `self.alive = False` stops the accept loop and triggers `_graceful_shutdown()`, which waits for in-flight connections before exiting. The arbiter detects the exit and spawns a replacement.
- Jitter prevents all workers from restarting simultaneously in multi-worker deployments.
