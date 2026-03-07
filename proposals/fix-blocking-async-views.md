---
depends_on:
- server-architecture-review
packages:
- plain.server
related:
- fix-async-view-thread-affinity
---

# Fix: Blocking Async Views Freeze the Worker

## Finding

**Finding 6 from server-architecture-review.md — PARTIALLY RESOLVED (documentation exists for SSE, but not for general async views; no runtime guardrails)**

Each worker runs exactly one asyncio event loop (`asyncio.run(self.run())` at `thread.py:288`). Async views execute directly on this event loop. If an async view makes any blocking call — a sync ORM query, `time.sleep()`, a blocking HTTP client call — the entire event loop freezes. This means:

- No new connections can be accepted
- No keepalive timeouts fire
- No heartbeats are sent (the arbiter will eventually kill the worker)
- All other async tasks (SSE streams, H2 streams) stall

### Current state of documentation

The `ServerSentEventsView` documentation in `views/README.md:351` includes a warning:

> ServerSentEventsView only accepts GET requests. The `stream()` method runs on the event loop — use `await` for any I/O and avoid blocking calls. Use `await asyncio.sleep()` instead of `time.sleep()`, and `await loop.run_in_executor()` to wrap blocking operations.

However, this warning only covers the SSE-specific `stream()` method. There is **no equivalent warning** for:

- General async view handlers (any `async def get()`, `async def post()`, etc.)
- The server README's architecture section
- The views README's general view documentation

### Current state of runtime detection

There is **no** asyncio debug mode enabled, no `slow_callback_duration` monitoring, and no blocking-call detection anywhere in the server. The codebase has zero hits for `asyncio.get_event_loop().set_debug`, `PYTHONASYNCIODEBUG`, or `slow_callback`.

### Why this is especially dangerous in Plain

The entire Plain framework stack is synchronous:

- **ORM:** `Model.query.filter(...)`, `Model.query.get(...)` — all blocking
- **Sessions:** session reads/writes are blocking DB operations
- **Auth:** `get_request_user()` — blocking DB query
- **Templates:** Jinja2 rendering is CPU-bound and synchronous

A user writing `async def get(self)` in a view has no indication that calling `User.query.get(pk=1)` will freeze their server. The async view dispatch path (`base.py:171-186`) correctly awaits the coroutine on the event loop, but provides no protection against blocking calls within it.

## Proposed Fix

A two-part approach: improved documentation (immediate) and optional runtime detection (follow-up).

### Part 1: Documentation (immediate)

**File: `plain/plain/views/README.md`**

Add a prominent warning section about async views, placed near or within the existing view patterns section. Suggested content:

```markdown
### Async views

Any view method defined with `async def` runs directly on the worker's event loop. This enables non-blocking I/O patterns like `await asyncio.sleep()`, async HTTP clients, and `AsyncStreamingResponse`.

**Important:** Blocking calls in async views freeze the entire worker — no other requests can be processed until the blocking call returns. The Plain ORM, sessions, and auth layers are all synchronous. Do not call them from async views.

Common mistakes:
- `User.query.get(pk=1)` — blocks the event loop (use `await loop.run_in_executor(None, ...)` to wrap sync calls)
- `time.sleep(1)` — blocks the event loop (use `await asyncio.sleep(1)`)
- `requests.get(...)` — blocks the event loop (use `httpx.AsyncClient` or similar)

Use async views only when you need true async I/O (SSE, WebSockets, async HTTP clients). For standard request/response views that use the ORM, use regular sync views — they run in the thread pool and don't affect other connections.
```

**File: `plain/plain/server/README.md`**

In the Architecture section, add after the existing "Async views note":

```markdown
**Async view safety:** Async views run on the worker's single event loop. Any blocking call (sync ORM, `time.sleep()`, blocking HTTP) will freeze the entire worker. Use async views only for true async I/O patterns. Regular sync views run safely in the thread pool.
```

### Part 2: Runtime detection (follow-up)

**File: `plain/plain/server/workers/thread.py`**

Enable asyncio's built-in debug mode when Plain is in debug mode. This logs a warning whenever a callback blocks the event loop for more than a configurable threshold.

In `Worker.run()` (around line 290), before the main loop:

```python
async def run(self) -> None:
    loop = asyncio.get_running_loop()

    # Enable asyncio debug mode in development to detect blocking calls
    # in async views. Logs a warning when a callback takes > 0.1s.
    from plain.runtime import settings
    if settings.DEBUG:
        loop.set_debug(True)
        loop.slow_callback_duration = 0.1  # seconds

    # ... rest of run()
```

This leverages Python's built-in detection. When enabled, asyncio logs messages like:

```
WARNING:asyncio:Executing <Task ...> took 0.250 seconds
```

### Trade-offs

- **Documentation only** is zero-risk and addresses the most common path to this bug (users not knowing the constraint).
- **asyncio debug mode** adds a small performance overhead in development but catches real bugs. It should NOT be enabled in production (the overhead of debug mode includes extra bookkeeping per callback).
- **Not proposed:** Automatically wrapping async views in `run_in_executor`. This would defeat the purpose of async views (SSE, WebSocket) and add unnecessary overhead. The right answer is to keep the constraint explicit and well-documented.
- **Not proposed:** Async ORM/sessions/auth. This would be a massive undertaking and may not be warranted given Plain's design goals. The simpler path is: use sync views for ORM-heavy work, use async views only for streaming/SSE patterns.
