---
depends_on:
- server-architecture-review
packages:
- plain.server
---

# Server Architecture Fixes — Execution Plan

3 independent commits addressing all 12 findings from `server-architecture-review.md`. Each commit is self-contained and can be reviewed in any order.

**Baseline:** master at `322fd51cf2` (async I/O migration merged). HTTP/1.1 is fully async. H2 still uses reader threads and executor-based writes.

**Key existing infrastructure** (already in the codebase):

- `util.async_recv(sock, n)` — async recv for plain and SSL sockets (`util.py:191-210`)
- `util.async_sendall(sock, data)` — async sendall for plain and SSL sockets (`util.py:213-237`)
- `util._async_wait_readable(sock)` / `_async_wait_writable(sock)` — low-level fd waiters (`util.py:147-188`)
- `response.py` has `async_send_headers`, `async_write`, `async_write_response`, `async_close`
- `TConn.req_count` exists (`thread.py:211`) and is incremented at `thread.py:510`
- Sockets entering `async_handle_h2_connection` are already non-blocking (`thread.py:394`)

---

## Commit 1: Bring H2 I/O to parity with HTTP/1.1

**Findings covered:** #1, #2, #3, #4, #5, #7, #12
**Files modified:** `plain/plain/server/http/h2handler.py`, `plain/plain/server/workers/thread.py`
**Proposals:** `fix-h2-reader-threads.md`, `fix-h2-async-writes.md`, `fix-h2-ingress-queue.md`, `fix-h2-stream-concurrency.md`, `fix-h2-body-buffering.md`, `fix-h2-response-buffering.md`

### Part A: Replace reader thread with `util.async_recv` (Finding #5, #4)

The H2 handler spawns a `threading.Thread` per connection (`h2handler.py:327-344`) that runs `select()`/`recv()` and pushes data into an unbounded `asyncio.Queue`. HTTP/1.1 already uses `util.async_recv()` on the event loop. H2 should do the same. This also eliminates the unbounded queue (Finding #4).

**Delete from `async_handle_h2_connection`:**

- `recv_queue` declaration (`line 324`)
- `reader_stop = threading.Event()` (`line 325`)
- `_reader_thread` function (`lines 327-341`)
- `reader_thread` creation and `.start()` (`lines 343-344`)
- Reader thread cleanup in `finally` block (`lines 492-496`: `reader_stop.set()`, executor join, alive check)

**Delete unused imports:** `import select`, `import threading` (verify nothing else in the file uses them).

**Remove `sock.settimeout(30)`** (`line 320`). The socket is already non-blocking when it arrives (set at `thread.py:394`). This line switches it to blocking-with-timeout for the old executor-based writes. With async I/O, the socket must stay non-blocking.

**Replace the queue-based read** in the main loop (`lines 350-360`):

```python
# Before:
data = await asyncio.wait_for(recv_queue.get(), timeout=H2_IDLE_TIMEOUT)

# After:
data = await asyncio.wait_for(
    util.async_recv(sock, 65535),
    timeout=H2_IDLE_TIMEOUT,
)
```

Add import: `from .. import util` (add to existing import line if needed, or use `from ..util import async_recv, async_sendall`).

**Simplify the `finally` block** — no reader thread to stop/join:

```python
finally:
    for task in stream_tasks.values():
        task.cancel()
    if stream_tasks:
        await asyncio.gather(*stream_tasks.values(), return_exceptions=True)

    try:
        conn.close_connection()
        goaway_data = conn.data_to_send()
        if goaway_data:
            await util.async_sendall(sock, goaway_data)  # was run_in_executor
    except Exception:
        pass

    # _graceful_close uses blocking shutdown()/recv() with timeouts
    # for clean TCP teardown — keep it in the executor.
    await loop.run_in_executor(executor, _graceful_close, sock)
```

### Part B: Move H2 writes to async I/O (Finding #7)

`H2ConnectionState.flush()` (`h2handler.py:279-284`) uses `run_in_executor(self.executor, self.sock.sendall, outgoing)`, consuming a thread pool slot for every H2 frame write. HTTP/1.1 writes already use `util.async_sendall()`.

**Change `flush()`** (`lines 279-284`):

```python
async def flush(self) -> None:
    """Send any pending h2 data to the socket."""
    outgoing = self.conn.data_to_send()
    if outgoing:
        await asyncio.wait_for(
            util.async_sendall(self.sock, outgoing),
            timeout=30,
        )
```

The 30s timeout replaces the old `sock.settimeout(30)`. If a peer stops reading, the write times out and `TimeoutError` propagates to the connection loop, triggering cleanup. The existing 5s flow-control timeout in `_async_send_h2_data` (`line 693-696`) is a separate concern (waiting for window updates, not socket writes).

**Change connection preface** (`line 348`):

```python
# Before:
await loop.run_in_executor(executor, sock.sendall, conn.data_to_send())
# After:
await util.async_sendall(sock, conn.data_to_send())
```

**Note on `executor` parameter:** `executor` is still needed on `H2ConnectionState` for:

- `_collect_body()` / `next(response_iter, None)` — iterating response body (app code)
- `handler.handle()` dispatches app code into the executor internally
- `_graceful_close` in the finally block

### Part C: Configurable stream cap + worker-level budget (Findings #1, #2)

**Configurable stream cap (Finding #1):**

In `async_handle_h2_connection`, after `conn.initiate_connection()` (`line 308`):

```python
max_streams = getattr(settings, 'SERVER_H2_MAX_CONCURRENT_STREAMS', None)
if max_streams is not None:
    conn.update_settings({
        h2.settings.SettingCodes.MAX_CONCURRENT_STREAMS: max_streams,
    })
```

The h2 library defaults to 100 and enforces it. `update_settings()` after `initiate_connection()` sends a second SETTINGS frame — this is fine per the HTTP/2 spec and only happens when the user has configured a non-default value. The `settings` import already exists at line 310.

Add `import h2.settings` to the imports at the top of h2handler.py.

**Worker-level stream budget (Finding #2):**

In `Worker.__init__` (`thread.py`, around line 253), add:

```python
self._h2_stream_budget: asyncio.Semaphore = asyncio.Semaphore(self.app.threads * 4)
```

Update the `async_handle_h2_connection` call site (`thread.py:399-406`) to pass it:

```python
await async_handle_h2_connection(
    conn.sock,
    conn.client,
    conn.server,
    self.handler,
    self.app.is_ssl,
    self.tpool,
    stream_budget=self._h2_stream_budget,
)
```

Update `async_handle_h2_connection` signature to accept `stream_budget: asyncio.Semaphore | None = None`. Store on `H2ConnectionState`:

```python
self.stream_budget = stream_budget
```

In `_async_handle_stream`, wrap the entire function body:

```python
async def _async_handle_stream(state, stream):
    if state.stream_budget is not None:
        await state.stream_budget.acquire()
    try:
        # ... entire existing body (lines 504-551) ...
    finally:
        if state.stream_budget is not None:
            state.stream_budget.release()
```

Using explicit acquire/release instead of `async with` to keep the existing try/except structure intact.

### Part D: Aggregate body memory budget (Finding #3)

In `H2ConnectionState.__init__` (`h2handler.py:250-270`), add:

```python
self.aggregate_body_size: int = 0
self.max_aggregate_body: int = max_body * 4
```

Update the constructor to accept `max_body: int`. Update `async_handle_h2_connection` to pass it:

```python
state = H2ConnectionState(conn, sock, client, server, handler, scheme, executor,
                          max_body=max_body, stream_budget=stream_budget)
```

In the `DataReceived` handler (`lines 380-419`), add an aggregate check before the per-stream check. The current three branches are:

1. Stream not found → acknowledge data
2. Per-stream cap exceeded → send 413, remove stream
3. Normal → write data to stream buffer

Insert between branches 1 and 2:

```python
elif state.aggregate_body_size + len(event.data) > state.max_aggregate_body:
    # Aggregate memory budget exceeded — reject this stream
    try:
        body = b"<h1>503 Service Unavailable</h1>"
        conn.send_headers(event.stream_id, [
            (":status", "503"),
            ("content-type", "text/html"),
            ("content-length", str(len(body))),
        ])
        conn.send_data(event.stream_id, body, end_stream=True)
    except h2.exceptions.ProtocolError:
        try:
            conn.reset_stream(event.stream_id)
        except h2.exceptions.ProtocolError:
            pass
    conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
    # Decrement aggregate for data already accumulated by this stream
    state.aggregate_body_size -= stream.data_size
    state.streams.pop(event.stream_id, None)
    log.warning("H2 aggregate body budget exceeded (%d bytes)", state.max_aggregate_body)
```

In the normal write branch (`lines 414-419`), also track the aggregate:

```python
stream.data_size += len(event.data)
state.aggregate_body_size += len(event.data)
stream.data.write(event.data)
```

In the 413 rejection path (`lines 388-413`), decrement the aggregate before popping:

```python
state.aggregate_body_size -= stream.data_size
state.streams.pop(event.stream_id, None)
```

**Decrement on stream completion:** In `_async_handle_stream`, add to the outermost finally block:

```python
finally:
    state.aggregate_body_size -= stream.data_size
    # ... existing cleanup or stream_budget release ...
```

This covers all completion paths (success, error, cancellation). The stream's `data_size` is known because it was fully accumulated before `_async_handle_stream` was called.

### Part E: Stream H2 responses when Content-Length is set (Finding #12)

In `_async_write_h2_response` (`h2handler.py:616+`), the non-streaming branch buffers the entire body via `_collect_body()`. When Content-Length is already present, we can stream chunks directly.

Replace the `else` branch at line 616:

```python
else:
    has_content_length = any(n == "content-length" for n, _ in response_headers)

    if has_content_length:
        # Content-Length already set — stream chunks directly
        async with state.write_lock:
            conn.send_headers(stream_id, response_headers)
            await state.flush()
            h2_resp.headers_sent = True

        response_iter = iter(http_response)
        while True:
            chunk = await loop.run_in_executor(executor, next, response_iter, None)
            if chunk is None:
                break
            if chunk:
                h2_resp.sent += len(chunk)
                await _async_send_h2_data(state, stream_id, chunk, end_stream=False)

        async with state.write_lock:
            conn.send_data(stream_id, b"", end_stream=True)
            await state.flush()
    else:
        # No Content-Length — must buffer to determine size
        def _collect_body() -> bytes:
            # ... existing code (lines 618-623) ...
        # ... rest of existing buffering logic ...
```

This reuses the same pattern as the `StreamingResponse` branch (`lines 591-615`).

### Validation for Commit 1

- `./scripts/server-test` — run the server conformance/load tests
- `curl --http2 https://localhost:8443/` (requires TLS) — verify basic H2
- Verify thread count stays flat under many H2 connections (no more reader threads)
- Verify SSE/streaming over H2 still works
- Verify large uploads are rejected with 413 (per-stream) and 503 (aggregate)
- Verify `_graceful_close` still works (connection teardown)

---

## Commit 2: Fix async view lifecycle and document constraints

**Findings covered:** #6, #8, #9
**Files modified:** `plain/plain/internal/handlers/base.py`, `plain/plain/server/workers/thread.py`, `plain/plain/views/README.md`, `plain/plain/server/README.md`
**Proposals:** `fix-blocking-async-views.md`, `fix-async-view-thread-affinity.md`, `fix-request-finished-streaming.md`

### Part A: Async view blocking detection (Finding #6)

In `Worker.run()` (`thread.py:296`), before the heartbeat loop:

```python
async def run(self) -> None:
    loop = asyncio.get_running_loop()

    # Enable asyncio debug mode in development to detect blocking calls
    # in async views. Logs a warning when a callback takes > 0.1s.
    from plain.runtime import settings
    if settings.DEBUG:
        loop.set_debug(True)
        loop.slow_callback_duration = 0.1

    # ... existing signal handlers + accept loops + heartbeat ...
```

When enabled, asyncio logs `WARNING:asyncio:Executing <Task ...> took 0.250 seconds` for any blocking call > 100ms on the event loop. Only active in DEBUG — no production overhead.

### Part B: Thread affinity — document the limitation (Finding #8)

**Decision: Document, don't fix.** The plan previously self-contradicted on this — proposing a single-thread executor, then realizing it can't guarantee the same thread as the first `_run_sync_pipeline` call which already ran on the shared pool. A true fix would require detecting async views before running `_run_sync_pipeline`, adding significant complexity for minimal practical benefit.

The practical impact is minimal: `close_old_connections` (the main `request_finished` handler) is idempotent per-thread, and OTel context is explicitly propagated via `_run_in_executor`.

Update the `_finish_pipeline` docstring (`base.py:240-247`):

```python
def _finish_pipeline(self, request, response, ran_before):
    """Run after-middleware and send request_finished signal.

    For sync views, this runs on the same thread as request_started
    (part of the single _run_sync_pipeline call).

    For async views, this runs in a separate executor call and may
    land on a different thread than request_started. Thread-local
    state from request_started is not guaranteed to be available.
    In practice this is safe because close_old_connections (the main
    signal handler) is idempotent per-thread and OTel context is
    explicitly propagated.
    """
```

### Part C: Documentation (Findings #6, #9)

**`plain/plain/views/README.md`** — Add a section about async view safety (find the appropriate location near existing view patterns):

```markdown
### Async views

Any view method defined with `async def` runs directly on the worker's event loop.
This enables non-blocking I/O patterns like SSE, WebSockets, and async HTTP clients.

**Important:** Blocking calls in async views freeze the entire worker process — no
other requests can be processed until the blocking call returns. Plain's ORM, sessions,
and auth layers are all synchronous and must not be called from async views.

Common mistakes:

- `User.query.get(pk=1)` — blocks the event loop
- `time.sleep(1)` — use `await asyncio.sleep(1)` instead
- `requests.get(...)` — use an async HTTP client instead

To wrap a blocking call safely: `await asyncio.get_running_loop().run_in_executor(None, blocking_fn)`

Use async views only for true async I/O (SSE, async HTTP clients). For standard
request/response views that use the ORM, use regular sync views — they run in the
thread pool and don't block other connections.

In development (`DEBUG=True`), the server enables asyncio debug mode which logs
warnings when a callback blocks the event loop for more than 100ms.
```

**`plain/plain/server/README.md`** — Add an async view safety note in the Architecture section:

```markdown
**Async view safety:** Async views run directly on the worker's event loop. Any
blocking call (sync ORM queries, `time.sleep()`, blocking HTTP clients) will freeze
the entire worker — no connections can be accepted or processed until the call returns.
Use async views only for true async I/O patterns. Regular sync views run in the thread
pool and are safe for all framework APIs.
```

**`plain/plain/signals/README.md`** (if it exists, or add to server README) — Add a note about `request_finished` timing:

```markdown
Note: `request_finished` fires after middleware completes but before the response body
is transmitted to the client. For streaming responses (SSE, large downloads), the signal
fires while data is still being sent. Use `response.close()` or `_resource_closers` if
you need a hook that runs after transmission completes.
```

### Validation for Commit 2

- `./scripts/test` — full test suite
- Verify async view (SSE) works with `DEBUG=True`
- Create a test view with `time.sleep(0.2)` in an async def, verify asyncio debug warning appears
- Review docstrings read clearly

---

## Commit 3: Improve worker health detection and recycling

**Findings covered:** #10, #11
**Files modified:** `plain/plain/server/workers/thread.py`
**Proposals:** `fix-worker-timeout.md`, `fix-worker-recycling.md`

### Part A: Executor health probe (Finding #10)

In the heartbeat loop in `Worker.run()` (`thread.py:316-328`):

```python
while self.alive:
    self.notify()
    if not self.is_parent_alive():
        break

    # Probe executor health: if a no-op can't complete within
    # the timeout, the thread pool is stalled. Stop heartbeating
    # so the arbiter will restart this worker.
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

**Notes:**

- `self.timeout` is `SERVER_TIMEOUT / 2` (set in `_spawn_worker` at `arbiter.py`). If a no-op can't complete in that time, the pool is truly stalled.
- Adds one task to the executor queue per heartbeat (every 1s). Negligible overhead.
- Catches complete pool exhaustion. Partial stalls (7 of 8 threads blocked) are not detected — that would require accessing private `ThreadPoolExecutor` internals.

### Part B: Worker recycling (Finding #11)

In `Worker.__init__` (`thread.py`, around line 253), add:

```python
self.max_requests: int = getattr(settings, 'SERVER_MAX_REQUESTS', 0)
self.max_requests_jitter: int = getattr(settings, 'SERVER_MAX_REQUESTS_JITTER', 0)
self.total_requests: int = 0

if self.max_requests and self.max_requests_jitter:
    import random
    self.max_requests += random.randint(-self.max_requests_jitter, self.max_requests_jitter)
    self.max_requests = max(1, self.max_requests)
```

Add a helper method to Worker:

```python
def _count_request(self) -> None:
    """Increment request count and trigger graceful shutdown if limit reached."""
    self.total_requests += 1
    if self.max_requests and self.total_requests >= self.max_requests:
        self.log.info(
            "Worker reached max requests (%d), initiating graceful shutdown",
            self.max_requests,
        )
        self.alive = False
```

**HTTP/1.1 counting:** In `_handle_connection`, after `conn.req_count += 1` (`line 510`), add:

```python
conn.req_count += 1
self._count_request()
```

**H2 stream counting:** H2 streams exercise the same app code paths as HTTP/1.1 requests and should count equally toward the recycling limit. Pass a callback to `async_handle_h2_connection`:

Update the call site (`thread.py:399-406`):

```python
await async_handle_h2_connection(
    conn.sock,
    conn.client,
    conn.server,
    self.handler,
    self.app.is_ssl,
    self.tpool,
    stream_budget=self._h2_stream_budget,
    on_stream_complete=self._count_request,
)
```

Update `async_handle_h2_connection` signature to accept `on_stream_complete: Callable[[], None] | None = None`. Store on `H2ConnectionState`:

```python
self.on_stream_complete = on_stream_complete
```

In `_async_handle_stream`, add to the outermost finally block (same finally as the aggregate body decrement and stream_budget release from Commit 1):

```python
finally:
    state.aggregate_body_size -= stream.data_size
    if state.stream_budget is not None:
        state.stream_budget.release()
    if state.on_stream_complete is not None:
        state.on_stream_complete()
```

**Thread safety:** `_count_request()` is called from the event loop (both HTTP/1.1 `_handle_connection` and H2 `_async_handle_stream` run as asyncio tasks). No lock needed. Setting `self.alive = False` stops the heartbeat loop on the next iteration, triggering `_graceful_shutdown()` which gives in-flight connections time to finish.

**New settings to document in `server/README.md`:**

```
SERVER_MAX_REQUESTS = 0            # 0 = disabled; restart worker after N requests
SERVER_MAX_REQUESTS_JITTER = 0     # random +/- variance to prevent thundering herd
```

### Validation for Commit 3

- `./scripts/server-test`
- Test executor probe: create a view that blocks all threads for longer than `SERVER_TIMEOUT`, verify worker gets restarted by the arbiter
- Test recycling: set `SERVER_MAX_REQUESTS=5`, make 6 requests, verify worker restarts
- Test H2 stream counting: make requests over H2, verify they count toward the limit
- Verify jitter: with `SERVER_MAX_REQUESTS=100` and `JITTER=50`, verify workers restart at different points

---

## Decisions Log

Decisions made during plan review, recorded for context:

1. **`async_sendall` / `async_recv` already exist** — Created in the async I/O migration commit. No need to create them. The H2 handler should import and use them, matching HTTP/1.1.

2. **Thread affinity (Finding #8): Document, don't fix.** A true fix requires detecting async views before running `_run_sync_pipeline` — too complex for the minimal practical impact (`close_old_connections` is idempotent per-thread, OTel context is propagated).

3. **Write timeout strategy: 30s timeout inside `flush()`.** Uses `asyncio.wait_for(..., timeout=30)` wrapping `async_sendall`. Replaces the old `sock.settimeout(30)` which doesn't apply to non-blocking sockets. Single point of control — all H2 frame writes go through `flush()`.

4. **H2 settings timing: `update_settings()` after `initiate_connection()`.** Only sends a second SETTINGS frame when the user configures a non-default value. The h2 library's default of 100 is already in the initial SETTINGS from `initiate_connection()`.

5. **H2 stream counting: Yes, count toward `SERVER_MAX_REQUESTS`.** H2 streams exercise the same app code (middleware, views, ORM queries). One H2 connection with 100 streams does 100 requests of work. Use a callback from `_async_handle_stream` to `Worker._count_request()`.

6. **Aggregate body budget decrement: In `_async_handle_stream` finally block.** The stream's `data_size` is known (fully accumulated before the task starts). Also decrement in 413/503 rejection paths in the `DataReceived` handler. This covers all paths explicitly.

7. **Socket stays non-blocking.** Remove `sock.settimeout(30)` from `async_handle_h2_connection`. The socket arrives non-blocking (`thread.py:394`), stays non-blocking for `util.async_recv`/`async_sendall`. `_graceful_close` runs in the executor and sets its own `settimeout(1.0)` — `settimeout` with a positive value switches back to blocking-with-timeout, which is correct for the clean shutdown sequence.

8. **`_graceful_close` stays in the executor.** It uses blocking `shutdown()`/`recv()` with timeouts for clean TCP teardown. After stream tasks are cancelled and GOAWAY is sent via async I/O, no more async I/O happens, so the blocking mode transition is safe.

9. **Commit ordering is independent.** Commits 2 and 3 don't depend on Commit 1. However, if Commits 1 and 3 are both applied, the `_async_handle_stream` finally block combines aggregate body decrement (Commit 1), stream budget release (Commit 1), and `on_stream_complete` callback (Commit 3). If implementing together, combine them in one finally block. If separate, Commit 3 adds the callback to whatever finally block exists at that point.
