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

## The stack

| Layer            | Status                                                                                              |
| ---------------- | --------------------------------------------------------------------------------------------------- |
| HTTP/1.1 parsing | Gunicorn parser (pure Python, vendored). Native parser eventually (see `plain-server-httptools.md`) |
| HTTP/2           | Implemented via `h2` library with ALPN negotiation on TLS connections                               |
| HTTP/3           | Not needed — reverse proxies handle this                                                            |
| SSE              | Implemented — `ServerSentEventsView` with `async def stream()`                                      |
| WebSocket        | Not yet — `WebSocketView` with async lifecycle methods                                              |
| TLS              | Python `ssl` module, required for HTTP/2 ALPN                                                       |

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
