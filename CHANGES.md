# PR: Server Architecture — Realtime, HTTP/2, WebSockets

## What this PR does

This branch adds three new capabilities to Plain's built-in server:

1. **Realtime (SSE + Postgres LISTEN/NOTIFY)** — server-to-client push with zero new infrastructure
2. **WebSocket support** — bidirectional messaging for cases that need it
3. **HTTP/2** — multiplexed streams over a single connection, auto-negotiated via ALPN

All three run on the same port, in the same process, alongside regular HTTP traffic.

## User-facing changes

### New APIs users will write code against

**`plain.realtime.SSEView`** — define a view that pushes events to the browser via Server-Sent Events. All methods are sync (full ORM access). Register it in your URL router like any other view.

```python
from plain.realtime import SSEView

class UserNotifications(SSEView):
    def authorize(self):
        return self.request.user.is_authenticated

    def subscribe(self):
        return [f"user:{self.request.user.pk}"]

    def transform(self, channel_name, payload):
        return {"type": "update", "data": payload}
```

**`plain.realtime.notify()`** — send events from anywhere (views, jobs, signals, management commands).

```python
from plain.realtime import notify

notify("user:42", {"type": "new_comment", "comment_id": 7})
```

**`plain.views.WebSocketView`** — async view for bidirectional messaging. The one place in Plain where users write `async def`.

```python
from plain.views import WebSocketView

class ChatSocket(WebSocketView):
    async def authorize(self):
        return self.request.user.is_authenticated

    async def receive(self, message):
        await self.send(f"echo: {message}")
```

**`plain.realtime.RealtimeWebSocketView`** — WebSocketView with built-in Postgres LISTEN/NOTIFY subscription support.

```python
from plain.realtime import RealtimeWebSocketView

class ChatSocket(RealtimeWebSocketView):
    async def connect(self):
        await self.subscribe(f"chat:{self.url_kwargs['room_id']}")

    async def receive(self, message):
        await self.send(f"echo: {message}")
```

**Async view methods** — any view can now use `async def` for its HTTP methods. Opt-in per method — just make it async. Sync middleware still works (runs in an executor thread). The worker auto-detects async views and routes them to the event loop.

```python
from plain.views import View

class MyView(View):
    async def get(self):
        result = await some_async_api()
        return {"data": result}
```

**`plain.http.AsyncStreamingResponse`** — like `StreamingResponse` but takes an async iterator. Used internally by SSE, but also available directly for custom async streaming.

```python
from plain.http import AsyncStreamingResponse

async def generate():
    for i in range(100):
        yield f"chunk {i}\n"

return AsyncStreamingResponse(generate(), content_type="text/plain")
```

### New behavior (no code changes required)

- **HTTP/2** — automatic when SSL is enabled. Browsers negotiate it via ALPN. No configuration, no new settings. Falls back to HTTP/1.1 for older clients.

### New docs

- **`plain.realtime` README** — full documentation with SSEView, notify, authorization, WebSocket views, and patterns (notifications, dashboards, chat, AI streaming)
- **`plain.server` README** — expanded with real-time connections, HTTP/2, and scaling FAQs
- **`plain.views` README** — new WebSocketView section
- **`plain.http` README** — new AsyncStreamingResponse section, cross-reference to realtime for SSE
- **`scripts/` README** — new server testing section (h2spec, autobahn-wstest, server-test, server-bench)

### New package dependency

- `plain-realtime` — new installable package for SSE and realtime WebSocket views
- `h2` — added to the core `plain` package for HTTP/2 support

### No breaking changes

Existing views, middleware, and server configuration are unaffected. The worker loop internals changed (selectors → asyncio) but the external behavior is identical for regular HTTP requests.

## Architecture overview

```
                          ┌─────────────────────────────────────┐
                          │          Worker Process              │
                          │                                     │
   incoming               │  ┌───────────────┐                  │
   connection ────────────┼─>│  Main Thread   │                  │
                          │  │  (accept loop) │                  │
                          │  └───────┬───────┘                  │
                          │          │                           │
                          │          ├── HTTP/1.1 ──> Thread Pool (sync views)
                          │          │                           │
                          │          ├── HTTP/2 ────> H2 Handler (async, multiplexed)
                          │          │                           │
                          │          └── Upgrade ───> Event Loop (SSE / WebSocket)
                          │                              │       │
                          │                    ┌─────────┴─────┐ │
                          │                    │  asyncio loop  │ │
                          │                    │  - coroutines  │ │
                          │                    │  - heartbeats  │ │
                          │                    │  - PG listener │ │
                          │                    └───────────────┘ │
                          └─────────────────────────────────────┘
```

### The key infrastructure change: selectors → asyncio

The worker's main loop was rewritten. On master, the worker uses a `selectors`-based poller with a `PollableMethodQueue` (pipe-backed deque for cross-thread signaling) and manual keepalive tracking. This branch replaces all of that with `asyncio.run()` as the worker entry point:

```
Before (master):                        After (this branch):

selectors.DefaultSelector               asyncio.run()
├── accept listener sockets             ├── accept listener sockets
├── poll for keepalive events           ├── await keepalive events
├── PollableMethodQueue (pipe+deque)    ├── (removed — asyncio handles this)
└── ThreadPoolExecutor for requests     ├── ThreadPoolExecutor for requests
                                        └── event loop for SSE/WS/H2 handoff
```

This is the foundational change. Regular HTTP/1.1 requests still run on the thread pool exactly as before — the asyncio loop just replaces the selector as the orchestrator. But now the worker has an event loop that SSE, WebSocket, and H2 connections can be handed off to as lightweight coroutines.

## What changed, by area

### New: `plain.realtime` package

The core addition. Server-to-client push using Postgres LISTEN/NOTIFY as the event bus.

```
plain/plain/realtime/
├── __init__.py      # exports: SSEView, notify, pg_listen
├── channel.py       # SSEView class — authorize/subscribe/transform
├── listener.py      # SharedListener — one PG conn per worker, fans out to subscribers
└── notify.py        # notify() — thin wrapper around pg_notify()
```

**Key design decisions:**

- `SSEView` methods are all **sync** — full ORM/session access, no async in user code
- One Postgres LISTEN connection per worker (not per client)
- Events that fire inside a rolled-back transaction are never sent
- 8KB payload limit is fine — send a reference, client fetches details

### New: `plain.views.WebSocketView`

Async view class for bidirectional WebSocket communication.

```
plain/plain/views/websocket.py       # WebSocketView class
plain/plain/server/protocols/
├── websocket.py                     # WebSocket protocol (frame parsing, handshake)
└── sse.py                           # SSE protocol (event formatting, heartbeats)
```

WebSocketView is the **one place** in Plain where users write `async def`. This is intentional — WebSocket lifecycle is inherently async. SSE stays sync.

### New: HTTP/2 support

```
plain/plain/server/http/h2handler.py  # Full HTTP/2 handler (667 lines)
```

Auto-negotiated via ALPN when SSL is enabled. Uses the `h2` library. Passes 146/146 h2spec conformance tests. Falls back to HTTP/1.1 for clients that don't support it.

### Changed: `plain.server.workers.thread`

The biggest diff (+625/-303 lines). The worker's main loop was rewritten from `selectors` to `asyncio`:

- Removed `PollableMethodQueue` (pipe-based thread signaling)
- Removed `selectors.DefaultSelector` and manual keepalive deque
- `asyncio.run()` is now the worker entry point
- Socket handoff: sync auth/subscribe in thread pool, then transfer socket to event loop
- Connection tracking: `handed_off` flag prevents worker from closing sockets owned by the event loop

### Changed: `plain.internal.handlers.base`

The request handler gained awareness of `AsyncStreamingResponse` and `WebSocketUpgradeResponse` — it returns these marker types so the server knows to hand off the connection instead of writing a normal response.

### Changed: `plain.http.response`

Added `AsyncStreamingResponse` — an async generator-based streaming response used internally by SSE. Added `header_items()` shared between response types for H2 header emission.

## Test coverage

```
plain/tests/test_realtime.py          # 318 lines — SSEView, notify, listener, channels
scripts/h2spec                        # HTTP/2 conformance (146/146 passing)
scripts/autobahn-wstest               # WebSocket conformance (Autobahn test suite)
scripts/autobahn-report.py            # Parse Autobahn JSON results
```

## Dependency additions

- `h2` — HTTP/2 protocol library (added to `pyproject.toml`)

---

## This is too much for one PR

This branch has 22 commits and touches 36 files. Here's how to break it into independently mergeable phases:

### Phase 1: Asyncio worker loop (foundation)

**What:** Rewrite the worker's main loop from `selectors` to `asyncio`. No new features — regular HTTP/1.1 requests work exactly as before, just orchestrated by an asyncio event loop instead of a selector.

**Changes:**

- `plain/plain/server/workers/thread.py` — replace `selectors.DefaultSelector`, `PollableMethodQueue`, keepalive deque with `asyncio.run()` + event loop
- Remove `PollableMethodQueue` class entirely

**Why first:** Everything else (SSE, WebSocket, H2) needs an event loop to hand connections off to. This change is purely mechanical — same behavior, different orchestration — so it can be validated by running the full test suite and confirming all existing HTTP behavior is unchanged.

**Risk:** Medium. Every request flows through the worker loop. But it's a 1:1 behavioral replacement.

### Phase 2: Realtime (SSE + Postgres LISTEN/NOTIFY)

**What:** The `plain.realtime` package — `SSEView`, `notify()`, `SharedListener`, and the SSE protocol handler.

**Changes:**

- `plain/plain/realtime/` — entire new package
- `plain/plain/server/protocols/sse.py` — SSE protocol
- `plain/plain/http/response.py` — `AsyncStreamingResponse`
- `plain/plain/views/base.py` — SSEView integration in view dispatch
- `plain/plain/internal/handlers/base.py` — `AsyncStreamingResponse` awareness
- `plain/tests/test_realtime.py` — tests
- `example/app/realtime.py` + `example/app/urls.py` — example usage

**Why second:** This is the headline feature. SSE + Postgres covers 90% of realtime use cases (notifications, dashboards, streaming AI). Once this lands, users get value immediately.

**Risk:** Medium. New code, but isolated — only activates on SSEView endpoints. Regular HTTP is unaffected.

### Phase 3: WebSocket support

**What:** `WebSocketView`, WebSocket protocol handler, upgrade handshake.

**Changes:**

- `plain/plain/views/websocket.py` — `WebSocketView` class
- `plain/plain/server/protocols/websocket.py` — WebSocket protocol (frame parsing, masking, close handshake)
- `plain/plain/views/__init__.py` — export `WebSocketView`
- `plain/plain/internal/handlers/base.py` — `WebSocketUpgradeResponse` awareness
- `scripts/autobahn-wstest` + `scripts/autobahn-report.py` — conformance tests

**Why third:** WebSocket is the "escape hatch" for cases SSE can't handle — high-frequency bidirectional messaging. Less common, more complex. Can ship after SSE is proven stable.

**Risk:** Medium. 396 lines of protocol code. Autobahn conformance suite validates correctness.

### Phase 4: HTTP/2

**What:** H2 handler with ALPN negotiation, multiplexed stream support.

**Changes:**

- `plain/plain/server/http/h2handler.py` — 667-line H2 handler
- `plain/plain/server/workers/thread.py` — ALPN detection, H2 dispatch
- `plain/pyproject.toml` — `h2` dependency
- `scripts/h2spec` — conformance tests

**Why last:** HTTP/2 is a performance/multiplexing improvement, not a new capability. Everything works fine over HTTP/1.1. This can land whenever, even much later.

**Risk:** Low-medium. Only activates when SSL + ALPN negotiates h2. HTTP/1.1 is completely unaffected. 146/146 h2spec passing.

### Dependency graph and merge order

```
Phase 1 ──→ Phase 2 ──→ Phase 3
 asyncio     Realtime    WebSocket
 worker      (SSE)
 loop    ──→ Phase 4
              HTTP/2
```

Phase 1 is the prerequisite. After that:

- **Phases 2, 3, 4 are independent of each other** and can ship in any order
- **Suggested order is 2 → 3 → 4** because SSE delivers the most user value, WebSocket extends it, and HTTP/2 is a nice-to-have

Each phase can be deployed to production independently. Users get value starting at Phase 2.
