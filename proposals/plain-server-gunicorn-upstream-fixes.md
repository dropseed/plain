# plain (server): Gunicorn Upstream Fixes

Plain's thread worker was forked from gunicorn's `gthread` worker circa late 2023. Gunicorn has since made several reliability and performance improvements (Jan-Feb 2026). We've ported the targeted fixes; these larger changes remain.

## Already ported

- **SSL handshake in worker thread** (gunicorn PR #3440) — `conn.init()` moved from `enqueue_req()` to `handle()` so SSL errors don't crash workers
- **Monotonic clock for keepalive timeouts** (gunicorn b43dc6d) — `time.monotonic()` instead of `time.time()` to avoid NTP jumps
- **`setblocking(True)` in `handle()`** (gunicorn 6696336) — Restore blocking mode for keepalive connections before parsing
- **`finish_body()` extraction** (gunicorn b43dc6d) — Refactored body-drain into a public method; not yet called on keepalive path (see below)

## Remaining: Lock-free PollableMethodQueue

Gunicorn commit 0186211. Replaces `RLock`-based synchronization with a pipe-based method queue for lock-free coordination between worker threads and main thread.

- `PollableMethodQueue` class using `os.pipe()` for wake-up signaling
- Non-blocking pipe (both ends) for BSD compatibility
- Unified event loop using single `poller.select()` — no more `futures.wait()`
- `finish_request()` runs on main thread via `method_queue.defer()` instead of as a future callback
- Removes `_lock` entirely
- ~8% perf improvement at high concurrency due to reduced lock contention

This is a significant rewrite of the event loop and synchronization model.

## Remaining: Thread pool exhaustion protection

Gunicorn commit b5f127e. Prevents slow clients from starving the thread pool.

- New connections wait up to 5s for data (`wait_for_data()` with `selectors`) before committing a thread pool slot
- If no data arrives, connection defers back to the poller (`_DEFER` sentinel)
- `pending_conns` deque tracks deferred connections
- `murder_pending()` cleans up timed-out pending connections
- Fixes a regression from gunicorn's v24 where connections were submitted directly to the thread pool after `accept()`

This also enables the explicit `finish_body()` call on keepalive — currently skipped because draining on a blocking socket without this protection could itself cause thread exhaustion from slow clients.

## Remaining: Request body discard on keepalive

Gunicorn commit b43dc6d. Before returning a keepalive connection to the poller, call `conn.parser.finish_body()` to drain unread body bytes. Without this, leftover body data makes the socket appear readable, causing spurious wake-ups.

The `finish_body()` method is already extracted and available. The call site in `handle()` was intentionally omitted because it runs on a blocking socket — a slow client that never finishes sending its body would block the worker thread indefinitely. Safe to add once thread pool exhaustion protection is in place.

## Not relevant

- **HTTP/2 support** (gunicorn fe18960c) — New feature, not a fix
- **uWSGI binary protocol** (gunicorn ac7296ec) — New feature, not a fix
- **HTTP 103 Early Hints** (gunicorn 75b46bf6) — New feature, not a fix

## Reference

- Gunicorn gthread source: `https://github.com/benoitc/gunicorn/blob/master/gunicorn/workers/gthread.py`
- Key issues: #3306, #3308, #3518
- Key PRs: #3440
