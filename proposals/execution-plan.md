---
depends_on:
  - server-architecture-review
packages:
  - plain.server
---

# Server Architecture Fixes — Execution Plan

3 independent commits addressing all 12 findings from `server-architecture-review.md`. Each commit is self-contained and can be reviewed in any order.

**Baseline:** master at `322fd51cf2` (async I/O migration merged). HTTP/1.1 is fully async. H2 still uses reader threads and executor-based writes.

---

## Commit 1: Bring H2 I/O to parity with HTTP/1.1 ✅ DONE

**Findings covered:** #1, #2, #3, #4, #5, #7, #12
**Files modified:** `h2handler.py`, `thread.py`, `response.py`, `unreader.py`, `util.py`
**Proposals:** `fix-h2-reader-threads.md`, `fix-h2-async-writes.md`, `fix-h2-ingress-queue.md`, `fix-h2-stream-concurrency.md`, `fix-h2-body-buffering.md`, `fix-h2-response-buffering.md`

### What was planned vs what was built

The original plan assumed `util.async_recv`/`util.async_sendall` on raw sockets would work for H2. During implementation, we discovered that Python's `ssl.SSLSocket` with manual `add_reader`/`add_writer` silently loses data on long-lived H2 connections (56/146 h2spec failures). This forced a broader change: replacing the entire TLS layer with asyncio's native transport (`loop.create_connection` + `loop.start_tls` with memory BIO).

### What was implemented

**TLS layer (new — not in original plan):**

- Replaced blocking `_do_tls_handshake` (thread pool) with `_async_tls_handshake` using `loop.create_connection(sock=raw_socket)` + `loop.start_tls(ssl_ctx, server_side=True)`
- All connections (H1 and H2) now use `asyncio.StreamReader`/`StreamWriter` for TLS
- Added `reader`, `writer`, `_keepalive_byte` fields to `TConn`
- `TConn.close()` dispatches to `writer.close()` or `util.close(sock)` depending on connection type

**H1 I/O abstractions (new — not in original plan):**

- Added `_conn_recv()`, `_conn_sendall()`, `_conn_write_error()` module-level helpers that dispatch between StreamWriter and raw socket
- All H1 reads/writes go through these instead of `util.async_recv`/`util.async_sendall`
- `_wait_readable` handles streams via `reader.read(1)` + `_keepalive_byte` storage
- `response.py` added `_async_send()` method using the writer

**Part A — Reader thread elimination (as planned, different mechanism):**

- Removed `recv_queue`, `reader_stop`, `_reader_thread`, thread creation/join
- Removed `import select`, `import threading`
- Reads via `reader.read(65535)` instead of `util.async_recv(sock, 65535)`

**Part B — H2 async writes (as planned, different mechanism):**

- `H2ConnectionState` takes `writer: asyncio.StreamWriter` instead of `sock: socket.socket`
- `flush()` uses `self.writer.write(outgoing)` + `await self.writer.drain()` instead of `util.async_sendall`
- Connection preface sent via `state.flush()` instead of `run_in_executor`
- Removed `_graceful_close()` entirely — replaced with `writer.close()` + `writer.wait_closed()`

**Part C — Stream cap + budget (as planned):**

- `SERVER_H2_MAX_CONCURRENT_STREAMS` setting via `conn.update_settings()`
- Worker-level `asyncio.Semaphore(self.app.threads * 4)` passed to H2 handler
- `_async_handle_stream` wraps inner handler with budget acquire/release using `acquired` flag to handle cancellation during acquire

**Part D — Aggregate body budget (as planned, plus review fixes):**

- `aggregate_body_size` and `max_aggregate_body` on `H2ConnectionState`
- DataReceived handler: aggregate check (503), per-stream check (413), aggregate tracking
- `_reject_h2_stream()` helper extracted to deduplicate rejection logic
- StreamReset handler also decrements aggregate (found by review panel — prevents slow leak)

**Part E — Content-Length streaming (as planned, consolidated):**

- Merged Content-Length streaming into the existing FileResponse/StreamingResponse branch
- Only buffers via `_collect_body` when Content-Length is absent

### Review panel findings applied

The code went through 4 review passes (2 Claude reviewers). Key fixes:

- `TConn.close()` — prevented double-close when writer exists but is already closing
- `_async_handle_dispatch_error` — replaced direct `sock.shutdown()`/`sock.close()` with `conn.close()`
- TLS handshake failure — set `conn.handed_off = True` to prevent double-close of asyncio-owned fd
- StreamReset — decrement `aggregate_body_size` for streams still accumulating data
- `_async_send_h2_data` — await cancelled waiter tasks to prevent "Task destroyed" warnings
- `_async_handle_error` — pass `writer`/`is_ssl` to Response constructor for consistency
- H1 streaming — wrap `aclose()` in try/except to protect downstream cleanup

### Validation

- `./scripts/server-test` — 9/9 passed (32/32 h1spec, 146/146 h2spec, load tests, slowloris)
- `./scripts/pre-commit` — clean (all type checks, annotations, formatting)

---

## Commit 2: Fix async view lifecycle and document constraints

**Findings covered:** #6, #8, #9
**Files modified:** `plain/plain/internal/handlers/base.py`, `plain/plain/server/workers/thread.py`, `plain/plain/views/README.md`, `plain/plain/server/README.md`
**Proposals:** `fix-blocking-async-views.md`, `fix-async-view-thread-affinity.md`, `fix-request-finished-streaming.md`

### Part A: Async view blocking detection (Finding #6)

In `Worker.run()`, before the heartbeat loop:

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

**Decision: Document, don't fix.** A true fix requires detecting async views before running `_run_sync_pipeline` — too complex for the minimal practical impact (`close_old_connections` is idempotent per-thread, OTel context is propagated).

Update the `_finish_pipeline` docstring (`base.py`):

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

**`plain/plain/views/README.md`** — Add async view safety section.
**`plain/plain/server/README.md`** — Add async view safety note in Architecture section.
**`plain/plain/signals/README.md`** (or server README) — Add `request_finished` timing note.

### Validation for Commit 2

- `./scripts/test` — full test suite
- Verify async view (SSE) works with `DEBUG=True`
- Create a test view with `time.sleep(0.2)` in an async def, verify asyncio debug warning appears

---

## Commit 3: Improve worker health detection and recycling

**Findings covered:** #10, #11
**Files modified:** `plain/plain/server/workers/thread.py`
**Proposals:** `fix-worker-timeout.md`, `fix-worker-recycling.md`

### Part A: Executor health probe (Finding #10)

In the heartbeat loop in `Worker.run()`:

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

### Part B: Worker recycling (Finding #11)

Add `SERVER_MAX_REQUESTS` and `SERVER_MAX_REQUESTS_JITTER` settings. Add `Worker._count_request()` method that increments count and sets `self.alive = False` when limit is reached.

**HTTP/1.1 counting:** Call `self._count_request()` after `conn.req_count += 1`.

**H2 stream counting:** Pass `on_stream_complete=self._count_request` callback to `async_handle_h2_connection`. Store on `H2ConnectionState`. Call in `_async_handle_stream` finally block.

**Note (updated after Commit 1):** The `_async_handle_stream` finally block now uses an `acquired` flag pattern for budget semaphore release:

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

**Also note:** `_graceful_close` was removed in Commit 1. Connection teardown now uses `writer.close()` + `writer.wait_closed()`. The validation step about `_graceful_close` no longer applies.

### Validation for Commit 3

- `./scripts/server-test`
- Test executor probe: create a view that blocks all threads for longer than `SERVER_TIMEOUT`, verify worker gets restarted by the arbiter
- Test recycling: set `SERVER_MAX_REQUESTS=5`, make 6 requests, verify worker restarts
- Test H2 stream counting: make requests over H2, verify they count toward the limit
- Verify jitter: with `SERVER_MAX_REQUESTS=100` and `JITTER=50`, verify workers restart at different points

---

## Decisions Log

Decisions made during plan review, recorded for context:

1. **TLS layer change (updated).** The original plan assumed `util.async_recv`/`util.async_sendall` on raw sockets. Implementation revealed `ssl.SSLSocket` with `add_reader`/`add_writer` silently loses data on long-lived connections. Solution: asyncio transport layer (`create_connection` + `start_tls` with memory BIO) for ALL TLS connections, not just H2.

2. **Thread affinity (Finding #8): Document, don't fix.** A true fix requires detecting async views before running `_run_sync_pipeline` — too complex for the minimal practical impact (`close_old_connections` is idempotent per-thread, OTel context is propagated).

3. **Write timeout strategy: writer.drain() in flush().** H2 writes go through `writer.write()` + `writer.drain()`. asyncio's flow control handles backpressure. No explicit timeout wrapper needed — the connection-level idle timeout and flow-control timeout in `_async_send_h2_data` cover stall detection.

4. **H2 settings timing: `update_settings()` after `initiate_connection()`.** Only sends a second SETTINGS frame when the user configures a non-default value.

5. **H2 stream counting: Yes, count toward `SERVER_MAX_REQUESTS`.** H2 streams exercise the same app code. Use a callback from `_async_handle_stream` to `Worker._count_request()`.

6. **Aggregate body budget decrement: In `_async_handle_stream` finally block + StreamReset handler.** Covers all paths: normal completion, error, cancellation, and client-initiated reset before StreamEnded.

7. **`_graceful_close` removed (updated).** The original plan kept `_graceful_close` in the executor. With asyncio transport owning the socket, `writer.close()` + `writer.wait_closed()` handles clean teardown. No need for blocking `shutdown()`/`recv()` in an executor.

8. **Budget semaphore uses `acquired` flag (updated).** Prevents double-release when task is cancelled during `budget.acquire()`. The aggregate body decrement always runs (it was incremented in DataReceived before the task was created).

9. **Commit ordering is independent.** Commits 2 and 3 don't depend on Commit 1. The `_async_handle_stream` finally block structure is documented above for Commit 3 to build on.
