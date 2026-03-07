---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- fix-h2-async-writes
- fix-h2-ingress-queue
---

# Fix: HTTP/2 Per-Connection Reader Threads

## Finding

**Finding 5 from server-architecture-review.md — UNRESOLVED**

Each HTTP/2 connection spawns a dedicated `threading.Thread` for socket reading (`h2handler.py:327-344`). The reader thread runs a `select()`/`recv()` loop, pushing data into an `asyncio.Queue`. Thread count scales linearly with concurrent H2 connections.

This is confirmed in the current code:

```python
# h2handler.py:327-344
def _reader_thread() -> None:
    try:
        while not reader_stop.is_set():
            ready, _, _ = select.select([sock], [], [], 5.0)
            if not ready:
                continue
            data = sock.recv(65535)
            loop.call_soon_threadsafe(recv_queue.put_nowait, data)
            if not data:
                break
    except OSError as e:
        log.debug("H2 reader thread stopped: %s", e)
        loop.call_soon_threadsafe(recv_queue.put_nowait, None)

reader_thread = threading.Thread(target=_reader_thread, daemon=True)
reader_thread.start()
```

### Why it exists

HTTP/2 requires TLS (ALPN negotiation), so H2 sockets are always `ssl.SSLSocket`. Python's asyncio rejects `SSLSocket` in `loop.sock_recv()` — the codebase already works around this for HTTP/1.1 in `util.async_recv()` (lines 191-210) using manual non-blocking recv with `add_reader`/`add_writer`. The H2 handler chose a dedicated thread instead of this approach.

### Impact

Under many idle or long-lived H2 connections (common with browsers and HTTP/2 proxies that keep connections open for minutes), OS thread count grows proportionally. Each thread consumes ~8MB of virtual memory (default stack size on macOS/Linux). With `SERVER_CONNECTIONS=1000`, the worst case is 1000 reader threads consuming ~8GB of virtual address space, plus scheduler overhead.

The `H2_IDLE_TIMEOUT` of 300 seconds means connections (and their threads) persist for 5 minutes after the last stream ends.

## Proposed Fix

Replace the per-connection reader thread with event-loop-driven SSL socket reads, using the same `_async_wait_readable` / non-blocking `recv()` pattern already used by `util.async_recv()` for HTTP/1.1 SSL sockets.

### Specific changes

**File: `plain/plain/server/http/h2handler.py`**

1. **Remove** the `_reader_thread` function (lines 327-341), `reader_thread` creation (line 343-344), `reader_stop` event (line 326), and `recv_queue` (line 324).

2. **Remove** the reader thread cleanup in the `finally` block (lines 492-496).

3. **Replace** with an async reader coroutine that reads directly on the event loop:

```python
async def _async_read_h2_data(sock: socket.socket) -> bytes:
    """Read data from an H2 (SSL) socket on the event loop."""
    while True:
        try:
            return sock.recv(65535)
        except ssl.SSLWantReadError:
            await util._async_wait_readable(sock)
        except ssl.SSLWantWriteError:
            await util._async_wait_writable(sock)
        except BlockingIOError:
            await util._async_wait_readable(sock)
```

4. **Replace** the main loop's `recv_queue.get()` with direct async reads:

```python
# Before (current):
data = await asyncio.wait_for(recv_queue.get(), timeout=H2_IDLE_TIMEOUT)

# After (proposed):
data = await asyncio.wait_for(_async_read_h2_data(sock), timeout=H2_IDLE_TIMEOUT)
```

5. **Remove** `import threading` and `import select` if no longer used elsewhere in the file.

### Trade-offs

- **Positive:** Eliminates one OS thread per H2 connection. All I/O stays on the event loop, matching the HTTP/1.1 architecture and the stated design goal ("Move all server I/O to async event loop").
- **Positive:** Simpler code — no cross-thread queue, no `call_soon_threadsafe`, no `reader_stop` event, no thread join with timeout.
- **Neutral:** The `_async_read_h2_data` helper is essentially the same as `util.async_recv()` and could be unified or shared, but keeping it local avoids adding complexity to a utility module.
- **Risk:** The reader thread provided natural backpressure isolation — if the event loop was slow, the reader kept buffering in the queue. With event-loop reads, a slow event loop delays reads, which applies TCP-level backpressure to the client. This is actually desirable behavior (it matches HTTP/2 flow control semantics) but is a behavioral change.
- **Risk:** If `conn.receive_data()` or stream processing is slow, it delays the next `recv()`. In practice this is fine because `conn.receive_data()` is a sans-I/O parser (fast, no blocking), and stream task dispatch is just `create_task` (also fast). The actual application work happens in separate tasks.

### Validation

- Test with H2 clients (`h2load`, `curl --http2`) to verify no regressions.
- Monitor thread count under concurrent H2 connections — should stay flat regardless of connection count.
- Verify SSE/streaming over H2 still works (long-lived connections with idle periods).
