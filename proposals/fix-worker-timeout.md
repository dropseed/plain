---
packages:
  - plain.server
related:
  - fix-worker-recycling
---

# Fix: Worker timeout misses executor starvation (Finding 10)

## Status: UNRESOLVED

## Problem

The arbiter's `murder_workers()` (`arbiter.py:158-181`) kills workers when their heartbeat stops updating. The heartbeat runs on the worker's asyncio event loop (`worker.py:171-184`), ticking every 1 second via `asyncio.sleep(1.0)`.

If the thread pool is completely saturated (all threads blocked on slow DB queries, external HTTP calls, etc.), the event loop continues running and heartbeats continue. The arbiter sees a healthy worker even though no new requests can be processed.

**Key code locations:**

- `plain/plain/server/arbiter.py:158-181` — `murder_workers` checks heartbeat only
- `plain/plain/server/workers/worker.py:171-184` — heartbeat loop on event loop
- `plain/plain/server/workers/worker.py:109-113` — thread pool creation

## Impact

- All threads blocked = zero request throughput, but the worker appears alive
- The arbiter won't restart the worker because heartbeats continue
- This manifests as a "hanging" server that accepts connections but never responds
- Users would see timeouts at the load balancer / client level with no server-side alerts

## Proposed Fix

Add executor health monitoring to the heartbeat loop. Track whether the executor can complete work within a reasonable time.

### Changes

**`plain/plain/server/workers/worker.py`** — Add executor health check to heartbeat (around line 171):

```python
while self.alive:
    self.notify()
    if not self.is_parent_alive():
        break

    # Check executor health: submit a no-op and see if it completes
    # within a reasonable time. If not, the pool is stalled.
    try:
        await asyncio.wait_for(
            loop.run_in_executor(self.tpool, lambda: None),
            timeout=self.timeout,
        )
    except TimeoutError:
        self.log.warning(
            "Thread pool appears stalled (no-op didn't complete in %ss), "
            "stopping heartbeat to trigger arbiter restart",
            self.timeout,
        )
        # Stop heartbeating so the arbiter will kill us
        break

    # Surface accept-loop crashes
    for task in accept_tasks:
        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                self.log.error("Accept loop crashed: %s", exc)
                self.alive = False
                break

    await asyncio.sleep(1.0)
```

## Considerations

- The no-op lambda adds one task to the executor queue per heartbeat interval (1s). This is negligible overhead.
- The timeout should match `self.timeout` (which is `SERVER_TIMEOUT / 2`), so if the executor can't complete a no-op within that window, heartbeats stop and the arbiter will eventually kill the worker after `SERVER_TIMEOUT`.
- This doesn't detect partial stalls (e.g., 7 of 8 threads blocked). For that, you'd need to track executor queue depth or active thread count, which is more complex. The no-op approach catches the most critical case: complete pool exhaustion.
- An alternative is to track `ThreadPoolExecutor._work_queue.qsize()`, but that accesses a private attribute and is less reliable.
