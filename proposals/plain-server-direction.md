---
packages:
- plain.server
related:
- plain-server-httptools
- plain-server-middleware-boundary
---

# Plain server direction

## Philosophy

Plain owns the server. Users don't pick between Gunicorn and Uvicorn, don't learn ASGI, don't configure worker classes, don't set up Nginx for protocol support. The server disappears as a concept.

This is a genuine differentiator. Django requires an external ASGI server for async. Starlette/FastAPI are async-first, penalizing the sync majority. Plain is sync-first with async where it's needed, and the server knows the difference.

## Architecture

The server is vertically integrated — one system from socket accept to view dispatch.

- **asyncio event loop** accepts connections, manages keepalive, handles long-lived streams
- **Thread pool** handles sync views (the common case) with zero async overhead
- **Two-phase middleware** (`before_request`/`after_response`) stays sync always — no bridging needed
- **View-type dispatch** at the server level — the worker resolves the URL, checks the view class, and picks the execution context

No ASGI protocol layer. No protocol boundary between server and framework. Direct method calls.

## Layers and boundaries

Three layers, each with a clear responsibility:

| Layer          | Owns                                                       | Runs on     |
| -------------- | ---------------------------------------------------------- | ----------- |
| **Server**     | Protocol correctness, resource protection                  | Event loop  |
| **Handler**    | Orchestration (run middleware, resolve URL, dispatch view) | Thread pool |
| **Middleware** | Application policy and state                               | Thread pool |

### Server

The server handles things that are about HTTP as a protocol and protecting the process from abuse:

- Connection accept, TLS handshake, keep-alive
- HTTP parsing and framing (request line, headers, body, chunked encoding)
- Connection limits, header/body size limits, timeouts (slowloris)
- Health check responses (pre-thread-pool)
- Content-Length on response write
- H2 multiplexing and flow control

The server does not import application settings (beyond server configuration like bind/workers/threads/timeouts) and does not access application state.

### Handler

The handler is the bridge between server and application. It does as little as possible:

- Create OTel span
- Run before_request middleware chain
- Resolve URL, instantiate view, dispatch
- Run after_response middleware chain (reverse order)

No business logic. No policy decisions. Just connect the pieces.

### Middleware

Middleware handles anything that requires application configuration, state, or routing:

- Security policy (CSRF, host validation, HTTPS redirect)
- Session management
- Database connection lifecycle
- Default response headers from settings
- URL-based redirects (slash append, DB-backed redirects)
- User-installed middleware (admin, auth, etc.)

### Decision test

**"If the thread pool is fully saturated, should this still work?"**

- Yes — it belongs in the server (health checks, protocol handling, resource limits)
- No — it belongs in middleware (anything needing settings, DB, routing, sessions)

### Proxy deployment

The server is designed to work correctly when directly exposed to the internet, but the common production deployment will have a reverse proxy (nginx, Caddy, cloud load balancer) in front.

The principle is: **design for direct exposure, be harmlessly redundant when proxied.** No modes, no conditional behavior. If the proxy already handles HTTPS redirect, the server's redirect logic simply never fires. If the proxy validates hosts, the server validates too (defense in depth).

The only proxy-specific concern is trusting forwarded headers (`X-Forwarded-Proto`, `X-Forwarded-For`, `X-Forwarded-Host`). This is a configuration knob (trusted proxy IPs), not an architectural mode switch, and belongs in request construction.

## The stack

| Layer            | Status                                                                                              |
| ---------------- | --------------------------------------------------------------------------------------------------- |
| HTTP/1.1 parsing | Gunicorn parser (pure Python, vendored). Native parser eventually (see `plain-server-httptools.md`) |
| HTTP/2           | Implemented via `h2` library with ALPN negotiation on TLS connections                               |
| HTTP/3           | Not needed — reverse proxies handle this                                                            |
| SSE              | Implemented — `ServerSentEventsView` with `async def stream()`                                      |
| WebSocket        | Not yet — `WebSocketView` with async lifecycle methods                                              |
| TLS              | asyncio transport (`loop.start_tls` with memory BIO), required for HTTP/2 ALPN                      |

## Key dependencies

These are **protocol codecs**, not servers. They do zero I/O. Plain stays in control of connections, dispatch, everything.

- **`h2`** (+ `hpack`, `hyperframe`) — HTTP/2 framing, stream multiplexing, HPACK compression, flow control. Pure Python. Already integrated.
- **`wsproto`** or similar — WebSocket framing. Sans-I/O. (TBD which library.)
- **Native HTTP/1.1 parser** (eventual) — httptools or own Rust wrapper over httparse. Not blocking anything — the gunicorn parser works fine.

## What users see

Sync views stay sync. No async keywords, no changes:

```python
class DashboardView(View):
    def get(self):
        return TemplateResponse(...)
```

SSE is one async method (implemented):

```python
class NotificationsView(ServerSentEventsView):
    async def stream(self):
        while True:
            yield ServerSentEvent(data={"count": Notification.query.count()})
            await asyncio.sleep(5)
```

WebSocket is async lifecycle methods:

```python
class ChatView(WebSocketView):
    async def receive(self, message):
        await self.send(f"echo: {message}")
```

The async boundary is at the view level, not the framework level. Middleware, ORM, templates — all stay sync.

## Why not ASGI

ASGI is an interop protocol between independent servers and frameworks. Plain's server and framework are the same thing. Adding ASGI would insert a protocol boundary where none is needed, trading vertical integration for horizontal compatibility.

Plain could expose an ASGI handler later for specific ecosystem compatibility needs. But the core architecture should stay integrated. The features (SSE, WebSocket, HTTP/2, streaming) all work through ASGI — nothing is technically locked in. But the simplicity and control come from not having it.

## Non-goals

- **HTTP/3 / QUIC** — reverse proxies (Nginx, Caddy, Cloudflare) handle HTTP/3 to the browser. Plain speaks HTTP/2 to the proxy. This is how most of the internet works.
- **General async views** — async is for views that genuinely need the event loop (long-lived connections). Regular request-response views stay sync. No `async def get(self)` for a page that hits the database.
- **ASGI compatibility** — not a goal for the core. Possible as an adapter layer if ecosystem tooling demands it.
- **Async ORM / async psycopg** — sync ORM + `asyncio.to_thread()` covers the SSE use case. Free-threaded Python (when the ecosystem catches up) makes threads genuinely parallel, further reducing the case for async DB drivers.
- **`a`-prefix queryset methods** (`acount()`, `alist()`, etc.) — sync methods work via `to_thread()` from async code. Querysets can add `__aiter__` for `async for` without duplicating the API.

## Things that look concerning but are actually fine

- **H2 `conn` object accessed without write_lock from the main loop:** Since asyncio is single-threaded, `conn.receive_data()` and the event processing happen atomically between `await` points. Stream tasks can only interleave at `await`s. The h2 library is a sans-I/O state machine designed for this usage pattern.

- **`signal.signal()` for SIGABRT/SIGWINCH alongside asyncio:** These are intentional — SIGABRT needs immediate termination (not deferred to the event loop), and SIGWINCH is a no-op. Both are set on the main thread which is correct.

- **Thread pool shared between H1 and H2:** This is by design. The thread pool is the concurrency limiter. H2 streams naturally queue in the executor like H1 requests. Worker-level `_h2_stream_budget` semaphore provides backpressure.

- **Graceful shutdown with `tpool.shutdown(wait=False)`:** This is fine because `_graceful_shutdown` already waits for connection tasks (which wrap the executor calls) with a timeout before shutting down the pool.

## Free-threaded Python

Python 3.14 promotes free-threading to Phase II (officially supported, opt-in, 5-10% overhead). The asyncio + thread pool design works with or without the GIL:

- Free-threading shifts deployment from many-workers-few-threads to fewer-workers-many-threads
- `SERVER_WORKERS` and `SERVER_THREADS` become the primary concurrency tuning knobs
- Strengthens the sync ORM + thread pool approach — no need for async psycopg

**Current blockers:** psycopg 3 does not support free-threaded Python (open issue #1095). asyncio had thread-safety issues in 3.13; fixed in 3.14. No code changes needed now — the architecture naturally benefits when the ecosystem catches up.
