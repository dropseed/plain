---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- remove-signals
---

# Fix: request_finished fires before streaming completes (Finding 9)

## Status: PARTIALLY RESOLVED (documented intentionally, but no alternative signal)

## Problem

`request_finished` is sent in `_finish_pipeline()` (line 250) before the response body is iterated. For streaming responses (SSE, large downloads), the signal fires while data is still being transmitted. The code has an explicit comment documenting this as intentional (lines 242-247).

**Key code locations:**

- `plain/plain/internal/handlers/base.py:234-251` - `_finish_pipeline` sends signal before body iteration
- `plain/plain/server/workers/thread.py:984-1025` - `_stream_async_response` iterates chunks after handler returns
- `plain/plain/server/workers/thread.py:897-918` - `_async_finish_request` writes response after handler returns

## Analysis

The current behavior is intentional and documented. The comment explains the rationale: `request_finished` fires in the same executor context as `request_started` so that `close_old_connections` runs on the correct thread. Moving it to after streaming would require it to fire on the event loop (different thread), breaking thread-local DB connection cleanup.

The practical impact is limited because:

1. `close_old_connections` is idempotent and the next `request_started` also calls it
2. OTel spans already wrap the full response lifecycle (the span at line 161-166 stays open until `handle()` returns, which is before streaming in the worker)

However, observability integrations that track "request duration" via `request_finished` will see incorrect timing for streaming responses -- they'll see the time to generate the response object, not the time to transmit it.

## Proposed Fix

No code change strictly required -- the current design is a reasonable trade-off. Two improvements:

### 1. Improve documentation (minimal)

Update the docstring and add a note in the signals README that `request_finished` fires after middleware but before response body transmission for streaming responses.

### 2. Add a response_completed callback (optional)

For integrations that need to know when transmission is truly done, add a callback mechanism on the response object rather than a new signal (signals have thread-affinity issues):

```python
# In _stream_async_response and _async_finish_request, after body is fully sent:
if hasattr(http_response, 'on_complete'):
    http_response.on_complete()
```

This is already partially addressed by `response._resource_closers` (line 190) and `http_response.close()` which fire after iteration. Integrations can hook into `close()` for post-transmission timing.

## Recommendation

Document the contract more prominently. The existing `close()` mechanism on responses already provides a post-transmission hook. No new signal is needed unless there's a concrete use case that `close()` doesn't cover.
