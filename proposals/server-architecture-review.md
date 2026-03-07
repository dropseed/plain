---
packages:
- plain.server
related:
- plain-server-direction
---

# Server Architecture Review (Post-AsyncIO Migration)

Review of the server architecture after the AsyncIO transition, focused on operational and architectural risks under real-world load.

**Last audited:** 2026-03-07 against current code on branch `claude/review-server-asyncio-X22KU`.

## Executive Summary

The AsyncIO migration modernized the request loop and enabled async views, SSE, and HTTP/2. The audit found 9 unresolved findings, 3 partially resolved, and 0 fully resolved. The most critical gaps are around HTTP/2 worker-level backpressure and memory controls. One finding from the original reviews was incorrect (h2 library already caps streams at 100 per connection).

## Findings

### 1. HTTP/2 per-connection stream concurrency ~~(Critical)~~ Low-Medium

**Status: PARTIALLY RESOLVED** | Proposal: [`fix-h2-stream-concurrency.md`](fix-h2-stream-concurrency.md)

**File:** `plain/plain/server/http/h2handler.py:306-307`

~~The original review claimed `max_concurrent_streams` defaults to ~4.3 billion (effectively unlimited). This is incorrect.~~ The h2 library (v4.x) defaults `max_concurrent_streams` to **100** and enforces it server-side — `TooManyStreamsError` (a `ProtocolError` subclass) is raised when a client exceeds the limit, and the connection loop at `h2handler.py:467` catches `ProtocolError` and terminates the connection.

**What remains:** No application-level semaphore exists, so all 100 streams dispatch to the thread pool simultaneously. This is reasonable but not tunable. Consider adding an optional `SERVER_H2_MAX_CONCURRENT_STREAMS` setting and a per-connection semaphore for defense-in-depth.

### 2. HTTP/2 connections bypass worker backpressure (Medium)

**Status: UNRESOLVED** | Proposal: [`fix-h2-stream-concurrency.md`](fix-h2-stream-concurrency.md)

**File:** `plain/plain/server/workers/thread.py:339,356`

The worker tracks `nr_conns` against `max_connections` (default 1000) for backpressure. An HTTP/2 connection counts as **1 connection** regardless of how many streams it multiplexes. With streams capped at 100 per connection (finding #1), the worst case is 1000 connections x 100 streams = 100,000 stream tasks queuing into the thread pool.

The `ThreadPoolExecutor` provides natural throttling (tasks queue when all threads are busy), but there's no mechanism to push back on new H2 streams when the worker is overloaded.

**Risk:** A modest number of H2 connections can generate far more concurrent work than the same number of H1 connections, with no feedback to clients.

**Fix:** Add a worker-level `asyncio.Semaphore(threads * N)` passed to the H2 handler to limit total in-flight H2 stream tasks.

### 3. HTTP/2 request bodies fully buffered in memory per stream (High)

**Status: UNRESOLVED** | Proposal: [`fix-h2-body-buffering.md`](fix-h2-body-buffering.md)

**File:** `plain/plain/server/http/h2handler.py:48,380-419`

Each H2 stream accumulates body data into `BytesIO` (`H2Stream.data`) until `StreamEnded`, only then dispatching to app code.

**Existing mitigations:**

- Per-stream size cap: `DATA_UPLOAD_MAX_MEMORY_SIZE` (default 10 MiB fallback) with 413 rejection
- Proper flow-control acknowledgment via `acknowledge_received_data`

**What's missing:**

- No aggregate memory budget across concurrent streams (100 streams x 10 MiB = 1 GB per connection)
- No disk spooling for large H2 bodies (unlike HTTP/1.1 which has `AsyncBridgeUnreader` for streaming)
- No incremental body consumption path for H2

**Fix:** Phase 1: Add per-connection aggregate body byte counter. Phase 2: Replace BytesIO with SpooledTemporaryFile for disk spill.

### 4. HTTP/2 ingress queue is unbounded (Medium)

**Status: UNRESOLVED** | Proposal: [`fix-h2-ingress-queue.md`](fix-h2-ingress-queue.md)

**File:** `plain/plain/server/http/h2handler.py:324,336`

The per-connection reader thread pushes socket frames into an `asyncio.Queue()` with no max size, using `put_nowait` which never blocks.

**Practical severity is moderate** (not high as originally stated) because:

- TCP flow control limits inbound rate naturally
- Each `recv()` returns at most 65535 bytes
- The event loop consumer (`conn.receive_data`) is fast CPU-bound parsing
- Reader thread uses `select()` with 5s timeout, doesn't spin

But the queue is genuinely unbounded, and under pathological conditions (blocked event loop) could grow without limit.

**Fix:** `asyncio.Queue(maxsize=16)` (~1MB ceiling) with blocking put from reader thread.

### 5. HTTP/2 uses one dedicated OS thread per connection (High)

**Status: UNRESOLVED** | Proposal: [`fix-h2-reader-threads.md`](fix-h2-reader-threads.md)

**File:** `plain/plain/server/http/h2handler.py:327-343`

Each H2 connection starts a `threading.Thread` running `select()`/`recv()` in a loop. Thread count scales linearly with concurrent H2 connections.

**Key insight from audit:** This is inconsistent with the existing codebase. `util.async_recv()` (lines 191-210) already handles SSL sockets without threads using manual non-blocking recv + `add_reader`/`add_writer`. The H2 handler could use the same pattern, eliminating OS threads entirely and unifying the I/O approach across H1 and H2.

**Risk:** Under many idle/long-lived H2 connections, thread count grows unbounded, increasing memory footprint and OS scheduler overhead.

**Fix:** Replace reader threads with event-loop-driven SSL socket reads using the existing `async_recv` pattern.

### 6. Blocking async views freeze the entire worker (High)

**Status: PARTIALLY RESOLVED** | Proposal: [`fix-blocking-async-views.md`](fix-blocking-async-views.md)

**File:** `plain/plain/server/workers/thread.py:288`

Each worker runs one asyncio event loop. Async views run directly on it. Any blocking call (sync DB query, `time.sleep()`, blocking HTTP) freezes the entire worker — no new connections accepted, no keepalive timeouts, no heartbeats.

**Partial mitigation exists:** The SSE docs (`views/README.md:351`) warn about blocking calls and recommend `await asyncio.sleep()` and `run_in_executor()`. However, this warning is SSE-specific — there is no equivalent warning for general async views in either the views README or server README. Zero runtime detection exists (no asyncio debug mode, no `slow_callback_duration` monitoring).

**Fix:**

1. Add documentation warnings to views README (general async section) and server README
2. Enable `loop.set_debug(True)` with `slow_callback_duration=0.1` when `settings.DEBUG` is True

### 7. Single shared thread pool is a choke point (Medium)

**Status: UNRESOLVED** | Proposal: [`fix-h2-async-writes.md`](fix-h2-async-writes.md)

**File:** `plain/plain/server/http/h2handler.py:284`

One `ThreadPoolExecutor(max_workers=SERVER_THREADS)` handles sync middleware/view execution, H2 socket flushes, TLS handshakes, and bridge-mode parsing.

HTTP/1.1 response writes have been moved to async I/O (`async_write_response` uses `util.async_sendall`), so this is partially mitigated on the HTTP/1 path. However, H2 socket writes still go through the executor (`state.flush()` calls `run_in_executor(..., sock.sendall, ...)`). Every H2 frame write consumes a thread pool slot.

**Fix:** Replace executor-based `sock.sendall` with `util.async_sendall()` in the H2 handler, matching the HTTP/1.1 path.

### 8. Async view lifecycle split across threads (Medium)

**Status: UNRESOLVED** | Proposal: [`fix-async-view-thread-affinity.md`](fix-async-view-thread-affinity.md)

**File:** `plain/plain/internal/handlers/base.py:167-186`

For async views, the pipeline makes two `_run_in_executor` calls: `_run_sync_pipeline` (signal + before-middleware + resolve) then `_finish_pipeline` (after-middleware + `request_finished`). `ThreadPoolExecutor` provides no guarantee these land on the same thread.

**Practical impact is limited** because `close_old_connections` is idempotent per-thread and OTel context is explicitly propagated via `_run_in_executor`. But thread-local state assumptions are technically violated.

**Fix:** Use a single-thread executor per async view request to guarantee thread pinning, or document the limitation explicitly.

### 9. `request_finished` fires before streaming completes (Low)

**Status: PARTIALLY RESOLVED** | Proposal: [`fix-request-finished-streaming.md`](fix-request-finished-streaming.md)

**File:** `plain/plain/internal/handlers/base.py:242-247`

`request_finished` fires in `_finish_pipeline()` before streaming response iteration. The code comment explicitly documents this as intentional, with sound rationale: firing on the same thread as `request_started` is important for thread-local DB connection cleanup. Responses already have `close()` as a post-transmission hook.

**No code change strictly needed.** The existing contract is reasonable but could be documented more prominently for middleware/observability authors.

### 10. Worker timeout misses executor starvation (Medium)

**Status: UNRESOLVED** | Proposal: [`fix-worker-timeout.md`](fix-worker-timeout.md)

**File:** `plain/plain/server/arbiter.py:158-181`, `plain/plain/server/workers/thread.py:310-322`

The heartbeat runs on the event loop (`asyncio.sleep(1.0)` loop) and only proves event loop liveness. If all thread pool threads are blocked, heartbeats continue and the arbiter sees a healthy worker with near-zero throughput.

**Fix:** Add a no-op executor probe to the heartbeat loop. If the probe can't complete within `self.timeout`, stop heartbeating to trigger arbiter restart.

### 11. No worker recycling after `max_requests` removal (Low)

**Status: UNRESOLVED** | Proposal: [`fix-worker-recycling.md`](fix-worker-recycling.md)

No recycling logic exists in the codebase. `conn.req_count` is tracked at `thread.py:501` but never checked against a limit. Workers only restart on crash or timeout.

**Fix:** Add optional `SERVER_MAX_REQUESTS` setting with jitter. Worker sets `self.alive = False` after the limit, triggering graceful shutdown.

### 12. HTTP/2 non-streaming responses fully buffered before send (Low)

**Status: UNRESOLVED** | Proposal: [`fix-h2-response-buffering.md`](fix-h2-response-buffering.md)

**File:** `plain/plain/server/http/h2handler.py:618-623`

`_collect_body()` does `b"".join(parts)` to materialize the full body before sending. This is needed to determine Content-Length when not set, but most responses already have Content-Length from the framework.

**Fix:** When Content-Length is already present, stream chunks directly (same pattern as the existing StreamingResponse path). Fall back to buffering only when Content-Length is absent.

## Things that look concerning but are actually fine

- **H2 `conn` object accessed without write_lock from the main loop:** Since asyncio is single-threaded, `conn.receive_data()` and the event processing happen atomically between `await` points. Stream tasks can only interleave at `await`s. The h2 library is a sans-I/O state machine designed for this usage pattern.

- **`signal.signal()` for SIGABRT/SIGWINCH alongside asyncio:** These are intentional — SIGABRT needs immediate termination (not deferred to the event loop), and SIGWINCH is a no-op. Both are set on the main thread which is correct.

- **Thread pool shared between H1 and H2:** This is by design. The thread pool is the concurrency limiter. H2 streams naturally queue in the executor like H1 requests. The issue is only that there's no backpressure from the thread pool back to H2 stream acceptance.

- **Graceful shutdown with `tpool.shutdown(wait=False)`:** This is fine because `_graceful_shutdown` already waits for connection tasks (which wrap the executor calls) with a timeout before shutting down the pool.

## Prioritized Remediation

| Priority | Finding                                    | Status     | Severity | Proposal                                                                 |
| -------- | ------------------------------------------ | ---------- | -------- | ------------------------------------------------------------------------ |
| 1        | H2 worker-level stream backpressure (#2)   | Unresolved | Medium   | [`fix-h2-stream-concurrency.md`](fix-h2-stream-concurrency.md)           |
| 2        | H2 aggregate body memory budget (#3)       | Unresolved | High     | [`fix-h2-body-buffering.md`](fix-h2-body-buffering.md)                   |
| 3        | H2 reader threads → event loop I/O (#5)    | Unresolved | High     | [`fix-h2-reader-threads.md`](fix-h2-reader-threads.md)                   |
| 4        | H2 ingress queue bound (#4)                | Unresolved | Medium   | [`fix-h2-ingress-queue.md`](fix-h2-ingress-queue.md)                     |
| 5        | Async view blocking docs + debug mode (#6) | Partial    | High     | [`fix-blocking-async-views.md`](fix-blocking-async-views.md)             |
| 6        | H2 socket writes → async I/O (#7)          | Unresolved | Medium   | [`fix-h2-async-writes.md`](fix-h2-async-writes.md)                       |
| 7        | Worker timeout executor probe (#10)        | Unresolved | Medium   | [`fix-worker-timeout.md`](fix-worker-timeout.md)                         |
| 8        | Async view thread affinity (#8)            | Unresolved | Medium   | [`fix-async-view-thread-affinity.md`](fix-async-view-thread-affinity.md) |
| 9        | `request_finished` streaming docs (#9)     | Partial    | Low      | [`fix-request-finished-streaming.md`](fix-request-finished-streaming.md) |
| 10       | Optional worker recycling (#11)            | Unresolved | Low      | [`fix-worker-recycling.md`](fix-worker-recycling.md)                     |
| 11       | H2 response chunked writes (#12)           | Unresolved | Low      | [`fix-h2-response-buffering.md`](fix-h2-response-buffering.md)           |
| 12       | Per-connection stream cap (#1)             | Partial    | Low-Med  | [`fix-h2-stream-concurrency.md`](fix-h2-stream-concurrency.md)           |
