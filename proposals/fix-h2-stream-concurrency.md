---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- fix-h2-body-buffering
---

# Fix Proposal: H2 Stream Concurrency and Worker Backpressure

Addresses findings 1 and 2 from the server architecture review.

## Finding 1: Unbounded HTTP/2 stream concurrency

### Review Claim (PARTIALLY CORRECT)

The review states `H2Configuration` uses a default `max_concurrent_streams` of ~4.3 billion and there is no cap on stream tasks.

### Verification Results

**The `max_concurrent_streams` claim is INCORRECT.** The h2 library (v4.3.0) defaults to `max_concurrent_streams=100`. This is advertised in the SETTINGS frame sent during `initiate_connection()`. The h2 library also **enforces** this server-side: when a client tries to open stream 101+, `conn.receive_data()` raises `TooManyStreamsError` (a subclass of `ProtocolError`), which is caught at `h2handler.py:467` and terminates the connection.

**The "no cap on stream tasks" claim is PARTIALLY CORRECT.** While the h2 protocol caps concurrent streams at 100, the server creates an asyncio task for each stream (`h2handler.py:424`) with no application-level semaphore. All 100 tasks can run concurrently, each submitting work to the thread pool. The `ThreadPoolExecutor` naturally limits actual thread concurrency, but 100 queued tasks per connection is reasonable (not the "thousands" the review suggests).

### What Remains Unresolved

1. **No configurable stream limit.** The default of 100 is reasonable but not tunable via Plain settings.
2. **No per-connection semaphore.** All 100 streams dispatch to the thread pool simultaneously. For CPU-bound or slow views, this could create a long executor queue.

### Recommended Fix

**Priority: Low-Medium** (not Critical as claimed — the h2 library already provides a reasonable default)

#### A. Make `max_concurrent_streams` configurable (optional, nice-to-have)

Add a `SERVER_H2_MAX_CONCURRENT_STREAMS` setting (default: 100, matching h2's default).

In `h2handler.py:306`:

```python
# Before:
config = h2.config.H2Configuration(client_side=False)

# After:
from plain.runtime import settings
max_streams = getattr(settings, 'SERVER_H2_MAX_CONCURRENT_STREAMS', 100)
config = h2.config.H2Configuration(client_side=False)
conn = h2.connection.H2Connection(config=config)
conn.update_settings({
    h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: max_streams,
})
```

#### B. Add a per-connection stream semaphore (recommended)

This prevents a single connection from flooding the thread pool, providing fairness when multiple connections share the same worker.

In `h2handler.py`, add to `H2ConnectionState.__init__`:

```python
self.stream_semaphore = asyncio.Semaphore(max_streams)
```

In `_async_handle_stream`, wrap the handler dispatch:

```python
async with state.stream_semaphore:
    http_response = await state.handler.handle(http_request, state.executor)
    # ... rest of stream handling
```

**Note:** This is defense-in-depth. The h2 library already caps streams at the protocol level, so the semaphore mainly provides a hook for future tuning (e.g., setting the semaphore lower than the protocol limit).

### Trade-offs

- Adding a semaphore introduces minor overhead per stream (asyncio.Semaphore acquire/release).
- A semaphore lower than `max_concurrent_streams` would cause h2 flow-control to back up (streams are "open" at the protocol level but waiting for the semaphore), which is actually fine — the client will see backpressure.

---

## Finding 2: HTTP/2 connections bypass worker backpressure

### Review Claim (PARTIALLY CORRECT)

The review states `nr_conns` counts connections not streams, so H2 multiplexing bypasses admission control.

### Verification Results

**The mechanism described is CORRECT:** `nr_conns` increments once per TCP connection at `thread.py:356` and decrements at `thread.py:540`. A single H2 connection counts as 1 regardless of stream count. Backpressure at `thread.py:339` (`nr_conns >= max_connections`) only gates new TCP accepts.

**The severity is LOWER than claimed.** With h2's default `max_concurrent_streams=100`, a single H2 connection generates at most 100 concurrent stream tasks. With `SERVER_CONNECTIONS=1000` (default), the worst case is 100,000 concurrent stream tasks — but this requires 1000 simultaneous H2 connections, which is itself unusual. More realistically, a few dozen H2 connections would produce a few thousand stream tasks, which the thread pool (default size = `app.threads`) handles by queuing.

**The `max_keepalived` bypass is CORRECT but low-impact.** H2 connections are long-lived by design (connection reuse is the whole point of HTTP/2), so `force_close()` semantics don't apply. The H2 idle timeout (`H2_IDLE_TIMEOUT=300s` at `h2handler.py:32`) serves the equivalent role.

### What Remains Unresolved

1. **No stream-aware backpressure.** The worker has no visibility into how many H2 streams are active across all connections.
2. **Memory accounting gap.** Each active stream can buffer up to `DATA_UPLOAD_MAX_MEMORY_SIZE` (or 10 MiB fallback) in request body data, but this isn't counted against any worker-level budget.

### Recommended Fix

**Priority: Medium** (not Critical — the thread pool provides natural throttling)

#### A. Global per-worker stream budget (recommended)

Add a worker-level semaphore that limits total concurrent H2 stream tasks across all connections.

In `thread.py`, add to `Worker.__init__`:

```python
# Limit total H2 streams across all connections.
# Default: 4x thread count provides enough pipeline depth
# without unbounded queuing.
self._h2_stream_budget = asyncio.Semaphore(self.app.threads * 4)
```

Pass this semaphore to `async_handle_h2_connection` and use it in `_async_handle_stream`:

```python
async def _async_handle_stream(state, stream):
    async with state.worker_stream_budget:
        # ... existing stream handling
```

This ensures the total number of in-flight H2 stream tasks across all connections is bounded, providing meaningful backpressure regardless of how many H2 connections are open.

#### B. Weight H2 connections in `nr_conns` (alternative, not recommended)

This would mean incrementing `nr_conns` by the number of active streams. However, this is complex (streams come and go rapidly) and conflicts with the TCP-level semantics of `nr_conns`. The semaphore approach in (A) is cleaner.

### Trade-offs

- A global stream budget means H2 connections compete with each other for dispatch slots. Under heavy H2 load, some streams will wait longer. This is the desired behavior (fairness).
- The budget should be >= thread count to avoid starving the executor. A value of `threads * 4` provides pipeline depth for I/O-bound requests.
- HTTP/1.1 connections are unaffected — they don't go through this semaphore.

---

## Summary

| Finding                            | Claimed Severity | Actual Severity | Status                                                                                                                    |
| ---------------------------------- | ---------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1. Unbounded H2 stream concurrency | Critical         | Low-Medium      | PARTIALLY RESOLVED by h2 library defaults (100 streams, enforced). No server-side semaphore exists.                       |
| 2. H2 bypasses worker backpressure | Critical         | Medium          | UNRESOLVED. `nr_conns` truly doesn't account for streams. Thread pool provides natural throttling but no explicit budget. |

The review's core observation about the mismatch between connection-level and stream-level admission control is valid. However, the h2 library's built-in enforcement at 100 streams significantly reduces the blast radius. The recommended fixes (per-connection semaphore + global stream budget) would close the remaining gaps.
