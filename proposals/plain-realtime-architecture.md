---
depends_on:
- plain-server-h2-websockets
packages:
- plain.server
- plain-models
related:
- plain-server-direction
---

# Realtime Architecture Plan

Based on the probes/server spike branch. This captures what to keep, what to rearchitect, and the target package layout.

## Package structure

Three layers:

### 1. `plain` (core) — pure protocol views

`SSEView` and `WebSocketView` move to `plain.views`. They're just views that hold connections open. No database dependency.

- `SSEView` becomes a generic async streaming view. Instead of hardcoding `pg_listen()`, it exposes a method users override to provide an async generator of events.
- `WebSocketView` stays roughly as-is — handles upgrade, frame protocol, lifecycle methods.
- SSE formatting (`format_sse_event`, `format_sse_comment`) stays in core (pure string formatting).
- WebSocket framing (`encode_frame`, `read_frame`, etc.) stays in core under `plain.server` or `plain.views` internals.

### 2. `plain-postgres` — database + Postgres utilities

The ORM plus Postgres-specific utilities that aren't modeling:

- `pg_notify()` — low-level SQL call, just a utility function
- Connection management, advisory locks, etc. as this package grows

### 3. `plain-realtime` — batteries-included realtime (depends on `plain-postgres`)

The sugar layer most people use:

- `notify()` — the user-friendly wrapper around `pg_notify()`
- `pg_listen()` — async generator that yields from Postgres LISTEN/NOTIFY
- `SharedListener` — per-worker singleton Postgres connection with ref-counted subscriptions
- Postgres-backed view subclasses (e.g. a subclass of `SSEView` that provides `subscribe()`/`transform()` wired to `pg_listen()`)

## Issues to resolve

### A. WebSocket sync/async API

SSE is implemented with `async def stream()` — the user writes async generators. WebSocket will likely also be async (`async def receive`, etc.) since it's inherently bidirectional and event-driven. The consistency question is resolved: both SSE and WebSocket use async user methods.

### C. WebSocket `subscribe()` is hollow

**Problem:** `WebSocketView.subscribe(channel)` just appends to `self._subscriptions`. It's `async def` but does no I/O. The actual Postgres subscription happens later when the server reads the list. This is a leaky abstraction.

**Fix:** When `plain-realtime` provides the Postgres-backed version, `subscribe()` should actually subscribe (start listening). In the core `WebSocketView`, `subscribe()` might not exist at all — it's a `plain-realtime` concern.

### D. WebSocket protocol code is split across three locations

**Problem:**

- Frame encoding/decoding → `plain.realtime.websocket`
- Connection handling (upgrade, frame loop) → `plain.server.workers.thread` (~130 lines)
- User-facing view → `plain.views.websocket`

**Fix:** Consolidate protocol code. Frame encoding + connection handling belong together in `plain.server` (they're server internals). The view in `plain.views` stays thin — just the user-facing lifecycle methods. Target layout:

```
plain/server/protocols/websocket.py   — framing + connection handler
plain/server/protocols/sse.py         — SSE formatting (maybe too small for its own file)
plain/views/websocket.py              — WebSocketView (user-facing)
plain/views/sse.py                    — SSEView (user-facing)
```

### E. `thread.py` size

H2 handling has been extracted to `h2handler.py`. SSE/async streaming is handled via `AsyncStreamingResponse` detected by the worker. `thread.py` is currently ~775 lines. WebSocket protocol handling should also be extracted when implemented.

### F. `psycopg` dependency is implicit

**Problem:** `plain.realtime.listener` imports `psycopg` at runtime but it's not in `plain`'s dependencies. It comes transitively via `plain-models`.

**Fix:** When `plain-realtime` becomes its own package, it declares `plain-postgres` as a dependency. Problem goes away naturally with the package split.

## What's done

- `ServerSentEventsView` is in `plain.views.sse` with a generic async generator API (no Postgres hardcoding)
- `AsyncStreamingResponse` in `plain.http`
- Middleware refactored to `before_request`/`after_response`
- Async view dispatch in the worker (detects async views, runs on event loop)
- H2 handler extracted to `h2handler.py`
- Background asyncio event loop per worker

## Remaining work

1. **WebSocket** — `WebSocketView` with async lifecycle methods, protocol code in `plain.server`
2. **`plain-realtime` package** — Postgres-backed sugar layer (`pg_listen`, `SharedListener`, `notify()`)
3. **`plain-postgres`** — Home for `pg_notify()` and other Postgres utilities outside the ORM
