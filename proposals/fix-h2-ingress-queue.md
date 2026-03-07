---
depends_on:
- fix-h2-reader-threads
packages:
- plain.server
related:
- fix-h2-body-buffering
---

# Fix: HTTP/2 Ingress Queue is Unbounded

## Status: UNRESOLVED

## Problem Summary

The per-connection reader thread pushes raw socket data into an `asyncio.Queue()` with no `maxsize`. The reader uses `loop.call_soon_threadsafe(recv_queue.put_nowait, data)`, which will never block regardless of how many items are queued.

If the event loop falls behind processing H2 frames (e.g., due to executor saturation, slow `conn.receive_data()`, or many concurrent streams), the queue grows without bound.

### Code references

- `plain/plain/server/http/h2handler.py:324` -- `recv_queue: asyncio.Queue[bytes | None] = asyncio.Queue()` -- no maxsize
- `plain/plain/server/http/h2handler.py:336` -- `loop.call_soon_threadsafe(recv_queue.put_nowait, data)` -- fire-and-forget, never blocks
- `plain/plain/server/http/h2handler.py:341` -- Same pattern for error sentinel
- `plain/plain/server/http/h2handler.py:335` -- Each `recv()` reads up to 65535 bytes

### Practical severity assessment

In practice, the risk is **moderate rather than critical** for these reasons:

1. **TCP flow control limits inbound rate.** The socket receive buffer is finite (typically 128KB-256KB on macOS/Linux). The reader thread can only `recv()` what the OS has buffered. Data doesn't materialize from nowhere -- the client must actually send it.

2. **`recv()` returns at most 65535 bytes per call.** So each queue entry is bounded in size.

3. **The event loop consumer is fast.** `conn.receive_data()` is CPU-bound parsing with no I/O, so it processes frames very quickly. The queue would only grow if the event loop is blocked by something else (which is a separate problem).

4. **The reader thread uses `select()` with a 5-second timeout.** It doesn't spin -- it waits for socket readiness.

However, the queue IS genuinely unbounded, and under pathological conditions (event loop blocked, client sending at high rate), memory could grow. The fix is simple and low-risk.

### What remains unaddressed

- No maxsize on the queue
- No backpressure from event loop to reader thread
- `put_nowait` can raise `QueueFull` if a maxsize is set, which is unhandled

## Proposed Fix

Replace the unbounded queue with a bounded one and handle the threading interaction correctly.

**File:** `plain/plain/server/http/h2handler.py`

### Option A: Bounded queue with blocking put (recommended)

Change line 324:

```python
# Before
recv_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

# After -- 16 entries * 65KB max = ~1MB buffered ceiling
recv_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=16)
```

Change `_reader_thread` (lines 327-341) to use blocking `put` instead of `put_nowait`:

```python
def _reader_thread() -> None:
    try:
        while not reader_stop.is_set():
            ready, _, _ = select.select([sock], [], [], 5.0)
            if not ready:
                continue
            data = sock.recv(65535)
            # Block until the event loop consumes entries.
            # This applies TCP-level backpressure: when the queue is full,
            # we stop reading from the socket, so the OS receive buffer fills,
            # and TCP flow control slows the sender.
            future = asyncio.run_coroutine_threadsafe(
                recv_queue.put(data), loop
            )
            try:
                future.result(timeout=30)
            except TimeoutError:
                log.warning("H2 reader: event loop not consuming frames, closing")
                loop.call_soon_threadsafe(recv_queue.put_nowait, None)
                break
            if not data:
                break
    except OSError as e:
        log.debug("H2 reader thread stopped: %s", e)
        try:
            loop.call_soon_threadsafe(recv_queue.put_nowait, None)
        except RuntimeError:
            pass
```

**Key points:**

- `recv_queue.put(data)` is an async coroutine, so from the reader thread we use `run_coroutine_threadsafe` and block on the future
- When the queue is full, the reader thread blocks, which stops `recv()` calls, which fills the OS socket buffer, which triggers TCP flow control -- natural backpressure
- The sentinel `None` (for EOF/error) still uses `put_nowait` since the consumer always drains promptly and we need the signal to arrive even if the queue is full
- A 30-second timeout prevents the reader thread from hanging forever if the event loop dies

### Option B: Simpler -- just catch QueueFull (lower complexity, weaker backpressure)

If the threading interaction of Option A is concerning, a simpler approach:

```python
recv_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=16)

def _reader_thread() -> None:
    try:
        while not reader_stop.is_set():
            ready, _, _ = select.select([sock], [], [], 5.0)
            if not ready:
                continue
            data = sock.recv(65535)
            while not reader_stop.is_set():
                try:
                    loop.call_soon_threadsafe(recv_queue.put_nowait, data)
                    break
                except asyncio.QueueFull:
                    # Queue full -- wait briefly and retry.
                    # This pauses recv(), applying TCP backpressure.
                    time.sleep(0.01)
            if not data:
                break
    except OSError as e:
        log.debug("H2 reader thread stopped: %s", e)
        loop.call_soon_threadsafe(recv_queue.put_nowait, None)
```

This is simpler but uses polling (sleep + retry) instead of proper async coordination.

## Sizing the Queue

- Each entry is at most 65535 bytes (one `recv()` call)
- `maxsize=16` gives ~1 MB worst-case buffer, which is more than enough to keep the pipeline fed
- The consumer (event loop) processes entries in microseconds, so the queue will rarely be more than 1-2 entries deep in normal operation
- Values of 8-32 are all reasonable; 16 is a safe default

## Trade-offs

- **Option A** provides proper backpressure but adds `run_coroutine_threadsafe` complexity in the reader thread
- **Option B** is simpler but uses polling which adds latency under backpressure
- Both options bound memory to ~1 MB per connection for the ingress queue
- The sentinel (`None`) must still be deliverable when the queue is full -- both options handle this
- Neither option changes the overall architecture or behavior under normal load
